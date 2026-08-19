"""
WeCom (企业微信) AI Bot: device-flow scan registration + message
sending via the official qyapi.weixin.qq.com/cli REST gateway.

Distinct from services/webhook/wechat.py (custom group-robot incoming
webhook, group-only, no per-person identity). This can DM a specific
person by userid directly, no pre-existing conversation required — that
mirrors what feishu_app/ does for Feishu, via a different (but also
REST, no persistent connection needed) protocol.

Both the device-flow endpoints and the /cli message gateway are not
covered by WeCom's own public developer documentation — confirmed live
end-to-end (scan -> botid/secret -> bearer token -> real message
delivered) against the real endpoints the official `wecom-cli`
(github.com/WecomTeam/wecom-cli) tool itself uses, same trust level as
the Feishu PersonalAgent device flow in feishu_app/device_registration.py.
"""
