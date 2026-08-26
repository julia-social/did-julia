import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from did_julia.chain import FullNodeClient  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


class FixtureClient(FullNodeClient):
    """Replays recorded RPC responses so tests run without a node."""

    def __init__(self, fixture_name: str):
        super().__init__(base_url="fixture://")
        with open(FIXTURES / fixture_name) as f:
            self._calls = json.load(f)

    def _post(self, method: str, payload: dict) -> dict:
        for call in self._calls:
            if call["method"] == method and call["payload"] == payload:
                return call["response"]
        raise AssertionError(f"no recorded RPC response for {method} {payload}")


@pytest.fixture
def mainnet_client() -> FixtureClient:
    return FixtureClient("rpc_calls_ArD2.json")


@pytest.fixture
def expected_resolution() -> dict:
    with open(FIXTURES / "expected_resolution_ArD2.json") as f:
        return json.load(f)
