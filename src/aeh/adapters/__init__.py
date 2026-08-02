from aeh.adapters.base import AgentAdapter
from aeh.adapters.mock import MockAdapter
from aeh.adapters.react import ReactAdapter
from aeh.adapters.replay import ReplayAdapter
from aeh.adapters.single_shot import SingleShotAdapter

ADAPTERS = {
    "mock": MockAdapter,
    "react": ReactAdapter,
    "single_shot": SingleShotAdapter,
    "replay": ReplayAdapter,
}

__all__ = [
    "ADAPTERS",
    "AgentAdapter",
    "MockAdapter",
    "ReactAdapter",
    "ReplayAdapter",
    "SingleShotAdapter",
]
