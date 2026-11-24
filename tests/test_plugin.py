from __future__ import annotations

import base64
import json
import unittest

import plugin


CONFIG = {
    "sessions": ["__client=first-fixture", "__client=second-fixture"],
    "models": list(plugin.DEFAULT_MODELS),
    "orgId": "org_fixture",
    "templateJam": "jam_template",
}


def provider(kind: str, **values):
    return {"kind": kind, **values}


def step(session_id: str, state: dict, status: int, body, config: dict = CONFIG):
    return plugin._provider_handler(
        plugin.CAPABILITY,
        config,
        provider("session_step", session_id=session_id, state=state,
                 response={"status": status, "body": body}),
    )


class CapyProviderTests(unittest.TestCase):
    def tearDown(self):
        plugin._cookie_cursor = 0
        with plugin._session_runtime_lock:
            plugin._session_runtime.clear()

    def test_free_model_filter_fails_closed(self):
        valid = {
            "id": "zai/glm-5.3-flash-ads", "ads": True, "auth": "capy", "byok": False,
            "unavailable": None, "route": {"kind": "capy", "locked": False, "skipped": None},
            "pricing": {"input": 0, "output": 0, "cacheRead": 0},
        }
        self.assertTrue(plugin._free_model(valid))
        paid = json.loads(json.dumps(valid))
        paid["pricing"]["output"] = 0.01
        self.assertFalse(plugin._free_model(paid))
        unmarked = json.loads(json.dumps(valid))
        unmarked["ads"] = False
        self.assertFalse(plugin._free_model(unmarked))

    def test_discovery_lists_only_configured_free_model_ids(self):
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG, provider("discover", limit=20))
        self.assertEqual([model["id"] for model in result["models"]], plugin.DEFAULT_MODELS)
        self.assertIsNone(result["next_cursor"])

    def test_tool_arguments_are_checked_against_the_declared_schema(self):
        state = {"decision": {
            "nonce": "nonce-1", "choice": "auto", "parallel": True,
            "tools": {"lookup": {"name": "lookup", "parameters": {
                "type": "object", "additionalProperties": False,
                "required": ["id"], "properties": {"id": {"type": "integer"}},
            }}},
        }, "answer": json.dumps({
            "protocol": "capy2api.tools.v1", "request_id": "nonce-1", "kind": "tool_calls",
            "calls": [{"name": "lookup", "arguments": {"id": 7}}],
        })}
        message, reason = plugin._decode_answer(state)
        self.assertEqual(reason, "tool_calls")
        self.assertEqual(json.loads(message["tool_calls"][0]["function"]["arguments"]), {"id": 7})
        state["answer"] = json.dumps({
            "protocol": "capy2api.tools.v1", "request_id": "nonce-1", "kind": "tool_calls",
            "calls": [{"name": "lookup", "arguments": {"id": "7", "extra": True}}],
        })
        with self.assertRaises(plugin.PluginError):
            plugin._decode_answer(state)

    def test_session_close_retries_child_cleanup_through_the_granted_endpoint(self):
        session_id = "close-fixture"
        with plugin._session_runtime_lock:
            plugin._session_runtime[session_id] = {"cookies": CONFIG["sessions"], "config": CONFIG}
        state = {
            "session_id": session_id, "phase": "receive", "jam_id": "child-jam",
            "org_id": "org_fixture", "t": "fixture-jwt",
            "config": {"api": "capy-api", "delete_after": True},
        }
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG, provider(
            "session_close", session_id=session_id, state=state, reason="cancelled",
        ))
        self.assertEqual(result["kind"], "request")
        self.assertEqual(result["endpoint_id"], "capy-api")
        self.assertEqual(result["path"], "/app/orgs/org_fixture/jams/delete")
        self.assertEqual(result["body"], {"jamIds": ["child-jam"]})
        self.assertEqual(result["headers"]["authorization"], "Bearer fixture-jwt")

    def test_session_close_does_not_delete_a_child_twice(self):
        session_id = "closed-fixture"
        with plugin._session_runtime_lock:
            plugin._session_runtime[session_id] = {"cookies": CONFIG["sessions"], "config": CONFIG}
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG, provider(
            "session_close", session_id=session_id,
            state={"session_id": session_id, "deleted": True,
                   "config": {"api": "capy-api", "delete_after": True}},
            reason="completed",
        ))
        self.assertEqual(result, {"kind": "response", "response": {}})

    def test_session_bootstrap_refreshes_cookie_then_revalidates_model(self):
        started = plugin._provider_handler(
            plugin.CAPABILITY,
            CONFIG,
            provider("session_start", model=plugin.DEFAULT_MODELS[0],
                     request={"messages": [{"role": "user", "content": "hello"}]}),
        )
        sid, state = started["session_id"], started["state"]
        self.assertEqual(started["action"]["endpoint_id"], "clerk")
        self.assertEqual(started["action"]["headers"]["cookie"], "__client=first-fixture")

        switched = step(sid, state, 401, {})
        self.assertEqual(switched["action"]["headers"]["cookie"], "__client=second-fixture")
        state = switched["state"]

        token = step(sid, state, 200, {"response": {"sessions": [{"id": "sess_fixture", "status": "active"}]}})
        state = token["state"]
        token = step(sid, state, 200, {"jwt": "fixture-jwt"})
        state = token["state"]
        self.assertEqual(token["action"]["headers"]["authorization"], "Bearer fixture-jwt")

        orgs = step(sid, state, 200, {"items": [{"id": "org_fixture"}]})
        state = orgs["state"]
        models = step(sid, state, 200, {"items": [
            {"id": plugin.DEFAULT_MODELS[0], "ads": True, "auth": "capy", "byok": False,
             "unavailable": None, "route": {"kind": "capy", "locked": False, "skipped": None},
             "pricing": {"input": 0, "output": 0, "cacheRead": 0}},
        ]})
        self.assertEqual(models["state"]["phase"], "jams")

    def test_paid_model_is_rejected_before_side_thread_creation(self):
        single_cookie = {**CONFIG, "sessions": ["__client=only-fixture"]}
        started = plugin._provider_handler(
            plugin.CAPABILITY,
            single_cookie,
            provider("session_start", model=plugin.DEFAULT_MODELS[0],
                     request={"messages": [{"role": "user", "content": "hello"}]}),
        )
        sid, state = started["session_id"], started["state"]
        # Advance Clerk and organization discovery using fixture responses.
        state = step(sid, state, 200, {"response": {"sessions": [{"id": "s", "status": "active"}] }}, single_cookie)["state"]
        state = step(sid, state, 200, {"jwt": "jwt"}, single_cookie)["state"]
        state = step(sid, state, 200, {"items": [{"id": "org_fixture"}]}, single_cookie)["state"]
        result = step(sid, state, 200, {"items": [
            {"id": plugin.DEFAULT_MODELS[0], "ads": True, "auth": "capy", "byok": False,
             "unavailable": None, "route": {"kind": "capy", "locked": False, "skipped": None},
             "pricing": {"input": 0, "output": 0.2, "cacheRead": 0}},
        ]}, single_cookie)
        self.assertEqual(result, {"kind": "abort", "code": "model_not_free"})

    def test_unavailable_free_model_retries_the_next_cookie(self):
        started = plugin._provider_handler(plugin.CAPABILITY, CONFIG, provider(
            "session_start", model=plugin.DEFAULT_MODELS[0],
            request={"messages": [{"role": "user", "content": "hello"}]},
        ))
        sid, state = started["session_id"], started["state"]
        first_cookie = started["action"]["headers"]["cookie"]
        state = step(sid, state, 200, {"response": {"sessions": [{"id": "s", "status": "active"}]}})["state"]
        state = step(sid, state, 200, {"jwt": "jwt"})["state"]
        state = step(sid, state, 200, {"items": [{"id": "org_fixture"}]})["state"]
        retry = step(sid, state, 200, {"items": []})
        self.assertEqual(retry["state"]["phase"], "clerk_client")
        self.assertNotEqual(retry["action"]["headers"]["cookie"], first_cookie)

    def test_realtime_answer_is_buffered_and_returned_as_openai_response(self):
        started = plugin._provider_handler(
            plugin.CAPABILITY,
            CONFIG,
            provider("session_start", model=plugin.DEFAULT_MODELS[0],
                     request={"messages": [{"role": "user", "content": "hello"}]}),
        )
        sid, state = started["session_id"], started["state"]
        state = step(sid, state, 200, {"response": {"sessions": [{"id": "s", "status": "active"}]}})["state"]
        state = step(sid, state, 200, {"jwt": "jwt"})["state"]
        state = step(sid, state, 200, {"items": [{"id": "org_fixture"}]})["state"]
        state = step(sid, state, 200, {"items": [
            {"id": plugin.DEFAULT_MODELS[0], "ads": True, "auth": "capy", "byok": False,
             "unavailable": None, "route": {"kind": "capy", "locked": False, "skipped": None},
             "pricing": {"input": 0, "output": 0, "cacheRead": 0}},
        ]})["state"]
        state = step(sid, state, 200, {"items": [{"id": "jam_template", "primaryMachine": {"kind": "device"}}]})["state"]
        state = step(sid, state, 200, {"id": "jam_child"})["state"]
        self.assertEqual(state["phase"], "ws_connect")
        state = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "connected"}}))["state"]
        self.assertEqual(state["phase"], "ws_auth")
        state = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "sent"}}))["state"]
        state = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "sent"}}))["state"]
        self.assertEqual(state["phase"], "message")
        state = step(sid, state, 200, {})["state"]
        self.assertEqual(state["phase"], "receive")

        frame = {"jamId": "jam_child", "type": "delta", "delta": {
            "type": "llm-event", "event": {"type": "step-finish", "usage": {"inputTokens": 5, "outputTokens": 2}},
        }}
        frames = [{"type": "text", "data_base64": base64.b64encode(json.dumps(frame).encode()).decode()}]
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "batch", "frames": frames}}))
        state = result["state"]
        self.assertEqual(state["phase"], "receive")

        frame["delta"]["event"] = {"type": "text-delta", "id": "t1", "text": "OK"}
        frames = [{"type": "text", "data_base64": base64.b64encode(json.dumps(frame).encode()).decode()}]
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "batch", "frames": frames}}))
        state = result["state"]
        frame["delta"]["event"] = {"type": "step-finish", "usage": {"inputTokens": 5, "outputTokens": 2}}
        frames = [{"type": "text", "data_base64": base64.b64encode(json.dumps(frame).encode()).decode()}]
        result = plugin._provider_handler(plugin.CAPABILITY, CONFIG,
            provider("session_step", session_id=sid, state=state,
                     response={"kind": "websocket", "event": {"type": "batch", "frames": frames}}))
        self.assertEqual(result["state"]["phase"], "cleanup_request")
        complete = step(sid, result["state"], 200, {"outcomes": [{"outcome": "ok"}]})
        self.assertEqual(complete["kind"], "complete")
        self.assertEqual(complete["response"]["choices"][0]["message"]["content"], "OK")
        self.assertEqual(complete["response"]["usage"]["completion_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
