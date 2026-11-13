"""Display names for industry-post publishers, keyed by host.

The one place that turns a post's host into a company name. The curated
manifest (``curated_company`` in post_details) wins over this map; a host not
listed here is shown as the host. Keys are hosts without ``www.``; a host
also matches through its parent domains (``security.example.com`` uses
``example.com``).
"""
from __future__ import annotations

from typing import Optional
from urllib.parse import urlsplit

PUBLISHERS: dict[str, str] = {
    "about.gitlab.com": "GitLab",
    "accomplish.ai": "Accomplish",
    "aikido.dev": "Aikido Security",
    "anthropic.com": "Anthropic",
    "aws.amazon.com": "AWS",
    "bishopfox.com": "Bishop Fox",
    "blog.cloudflare.com": "Cloudflare",
    "blog.google": "Google",
    "blog.talosintelligence.com": "Cisco Talos",
    "blog.trailofbits.com": "Trail of Bits",
    "cohere.com": "Cohere",
    "databricks.com": "Databricks",
    "developer.nvidia.com": "NVIDIA",
    "elastic.co": "Elastic",
    "endorlabs.com": "Endor Labs",
    "engineering.fb.com": "Meta",
    "engineering.ramp.com": "Ramp",
    "github.blog": "GitHub",
    "hadrian.io": "Hadrian",
    "hiddenlayer.com": "HiddenLayer",
    "huggingface.co": "Hugging Face",
    "microsoft.com": "Microsoft",
    "mindstudio.ai": "MindStudio",
    "openai.com": "OpenAI",
    "orca.security": "Orca Security",
    "portswigger.net": "PortSwigger",
    "projectzero.google": "Google Project Zero",
    "rapid7.com": "Rapid7",
    "research.jfrog.com": "JFrog",
    "securitylabs.datadoghq.com": "Datadog Security Labs",
    "semgrep.dev": "Semgrep",
    "shopify.engineering": "Shopify",
    "snyk.io": "Snyk",
    "socket.dev": "Socket",
    "sysdig.com": "Sysdig",
    "tenable.com": "Tenable",
    "unit42.paloaltonetworks.com": "Palo Alto Networks Unit 42",
    "wiz.io": "Wiz",
    "xbow.com": "XBOW",
    "xlab.tencent.com": "Tencent Xuanwu Lab",
}


def host(url: Optional[str]) -> Optional[str]:
    """"https://www.wiz.io/blog/x" -> "wiz.io"."""
    if not url:
        return None
    name = (urlsplit(url).hostname or "").lower()
    return name[4:] if name.startswith("www.") else name or None


def publisher_name(url: Optional[str], curated_company: Optional[str] = None) -> Optional[str]:
    """The company to show for a post: the curated name, the mapped name, or the host."""
    if curated_company and curated_company.strip():
        return curated_company.strip()
    name = host(url)
    if name is None:
        return None
    parts = name.split(".")
    for index in range(len(parts) - 1):
        mapped = PUBLISHERS.get(".".join(parts[index:]))
        if mapped:
            return mapped
    return name
