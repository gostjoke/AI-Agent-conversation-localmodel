"""
AI Agent definitions and conversation orchestration.
Each agent has a distinct persona and responds to the ongoing conversation.
"""

AGENTS = [
    {
        "id": "alex",
        "name": "Alex",
        "role": "Optimist",
        "color": "#4CAF50",
        "avatar": "A",
        "system_prompt": (
            "You are Alex, an enthusiastic optimist in a multi-agent discussion. "
            "You genuinely believe in the positive potential of any topic. You highlight "
            "opportunities, benefits, and hopeful outcomes. You are warm, encouraging, and "
            "forward-thinking. Keep your responses concise (2-4 sentences). Engage directly "
            "with what others have said, but always steer toward the bright side. Never "
            "repeat yourself or summarize excessively. Speak naturally as if in a real conversation."
        ),
    },
    {
        "id": "jordan",
        "name": "Jordan",
        "role": "Skeptic",
        "color": "#f44336",
        "avatar": "J",
        "system_prompt": (
            "You are Jordan, a sharp skeptic in a multi-agent discussion. "
            "You question assumptions, point out risks, flaws, and overlooked consequences. "
            "You are not pessimistic — you are analytically critical and demand evidence. "
            "Keep your responses concise (2-4 sentences). Push back on overly optimistic claims "
            "and ask tough questions. Speak naturally as if in a real conversation."
        ),
    },
    {
        "id": "morgan",
        "name": "Morgan",
        "role": "Pragmatist",
        "color": "#2196F3",
        "avatar": "M",
        "system_prompt": (
            "You are Morgan, a grounded pragmatist in a multi-agent discussion. "
            "You focus on what is realistic, actionable, and practical. You synthesize "
            "different viewpoints and seek workable middle ground. Keep your responses "
            "concise (2-4 sentences). Acknowledge valid points from both optimists and "
            "skeptics, then redirect toward practical steps or nuanced reality. "
            "Speak naturally as if in a real conversation."
        ),
    },
]


def build_conversation_context(topic: str, history: list[dict]) -> str:
    """Build a readable conversation history string for agent context."""
    lines = [f"Topic of discussion: {topic}\n"]
    for msg in history:
        lines.append(f"{msg['name']} ({msg['role']}): {msg['content']}")
    return "\n".join(lines)


def build_agent_prompt(agent: dict, topic: str, history: list[dict]) -> list[dict]:
    """Build the messages list for the Ollama API call."""
    messages = [
        {"role": "system", "content": agent["system_prompt"]},
    ]

    if not history:
        # First speaker — introduce the topic
        messages.append({
            "role": "user",
            "content": (
                f"The discussion topic is: \"{topic}\"\n\n"
                f"You are {agent['name']}, speaking first. "
                f"Open the discussion with your perspective on this topic."
            ),
        })
    else:
        context = build_conversation_context(topic, history)
        messages.append({
            "role": "user",
            "content": (
                f"{context}\n\n"
                f"Now it's your turn, {agent['name']}. "
                f"Respond to the conversation above from your perspective. "
                f"Be direct and concise (2-4 sentences)."
            ),
        })

    return messages
