"""ORM models + engine factories for the AI Insights tab.

The AI Insights backend uses two engines:
- A *write* engine bound to the existing app role (settings.database_url).
- A *read-only* engine bound to the `ai_agent` role (settings.ai_agent_db_url),
  used exclusively by the `query_database` tool.

See backend/agents/insights/db/session.py for the factories.
"""

from .models import (  # noqa: F401
    AISession,
    AIInsight,
    AgentMessage,
    AgentToolCall,
    AgentChart,
    AgentCitation,
    SkillInvocation,
    SkillReference,
    InsightThread,
    InsightSubscription,
)
