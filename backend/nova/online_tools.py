"""Curated launch directory for free or freemium online AI services.

Browser-only directory: each item is a public website link. No provider API, API key, SDK, automated login, or automatic prompt forwarding is used. Free access and availability may change.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/api/online-tools", tags=["online tools"])

_TOOLS = [
    {"id": "duck-ai", "name": "Duck.ai", "category": "AI chat", "url": "https://duck.ai/?origin=funnel_marketing_website__productshowcase", "access": "Free tier", "account": "No account required for basic use", "privacy": "DuckDuckGo says chats are anonymized and not used to train models; review current provider-specific terms before sharing sensitive data.", "notes": "Third-party models hosted through DuckDuckGo; daily usage limits may apply."},
    {"id": "chatgpt", "name": "ChatGPT", "category": "AI chat", "url": "https://chatgpt.com/", "access": "Free tier", "account": "Account typically required", "privacy": "External service; do not send secrets or credentials.", "notes": "Free-tier features and limits can change."},
    {"id": "gemini", "name": "Google Gemini", "category": "AI chat", "url": "https://gemini.google.com/", "access": "Free tier", "account": "Google account typically required", "privacy": "External service governed by Google's terms and settings.", "notes": "Availability and model limits vary by region and account."},
    {"id": "claude", "name": "Claude", "category": "AI chat", "url": "https://claude.ai/", "access": "Free tier", "account": "Account typically required", "privacy": "External service; review current data controls.", "notes": "Free usage limits apply."},
    {"id": "perplexity", "name": "Perplexity", "category": "AI search", "url": "https://www.perplexity.ai/", "access": "Free tier", "account": "Some use may require an account", "privacy": "External service; check current privacy settings.", "notes": "AI answers with web sources; free-tier limits may apply."},
    {"id": "huggingchat", "name": "HuggingChat", "category": "Open models", "url": "https://huggingface.co/chat/", "access": "Free access may be available", "account": "Account may be required", "privacy": "External hosted inference; review model and service terms.", "notes": "Model availability and capacity vary."},
    {"id": "copilot", "name": "Microsoft Copilot", "category": "AI chat", "url": "https://copilot.microsoft.com/", "access": "Free tier", "account": "Sign-in may be required for some features", "privacy": "External service governed by Microsoft terms.", "notes": "Features and limits can change."},
    {"id": "phind", "name": "Phind", "category": "Coding AI", "url": "https://www.phind.com/", "access": "Free access may be available", "account": "May require an account", "privacy": "External service; review current terms.", "notes": "Coding-focused AI search and assistance; current availability may change."},
    {"id": "duckduckgo-search", "name": "DuckDuckGo Search", "category": "Web search", "url": "https://duckduckgo.com/search", "access": "Free", "account": "No account required for basic search", "privacy": "DuckDuckGo says it does not track search history.", "notes": "Standard web search; AI answers are optional and separate."},
    {"id": "google-search", "name": "Google Search", "category": "Web search", "url": "https://www.google.com/search", "access": "Free", "account": "No account required for basic search", "privacy": "Google search is an external service.", "notes": "Search features and AI experiences vary by region."},
    {"id": "grok", "name": "Grok", "category": "AI chat", "url": "https://grok.com/", "access": "Free access may be available", "account": "Account typically required", "privacy": "External service; review current terms.", "notes": "Availability and free limits can change."},
    {"id": "deepseek", "name": "DeepSeek", "category": "AI chat", "url": "https://chat.deepseek.com/", "access": "Free web access may be available", "account": "Sign-in may be required", "privacy": "External service; review current data controls.", "notes": "Use the website directly; NOVA does not call DeepSeek APIs."},
    {"id": "qwen-chat", "name": "Qwen Chat", "category": "AI chat", "url": "https://chat.qwen.ai/", "access": "Free web access may be available", "account": "Sign-in may be required for some features", "privacy": "External service; review current terms.", "notes": "Hosted Qwen models; availability and limits can change."},
    {"id": "mistral-le-chat", "name": "Mistral Le Chat", "category": "AI chat", "url": "https://chat.mistral.ai/", "access": "Free tier may be available", "account": "Account may be required", "privacy": "External service; review current terms.", "notes": "Open the web app directly; no Mistral API integration in NOVA."},
    {"id": "meta-ai", "name": "Meta AI", "category": "AI chat", "url": "https://www.meta.ai/", "access": "Free access may be available", "account": "Availability and sign-in vary by region", "privacy": "External service governed by Meta terms.", "notes": "Regional availability can change."},
    {"id": "poe", "name": "Poe", "category": "Multi-model chat", "url": "https://poe.com/", "access": "Free quota may be available", "account": "Account typically required", "privacy": "External service; review current terms.", "notes": "Free message quota and model availability can change."},
]


@router.get("")
def list_online_tools():
    return {"tools": _TOOLS, "count": len(_TOOLS),
            "mode": "browser_only", "provider_api_calls": False, "api_keys_required": False, "automatic_prompt_forwarding": False, "notice": "This is a browser-only directory of public websites. NOVA does not call online AI provider APIs, require provider API keys, automate provider logins, or silently send local chat content. Free tiers, login requirements, regional availability, and privacy terms can change."}
