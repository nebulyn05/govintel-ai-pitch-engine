from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.orchestrator import _enqueue_csv


def test_csv_intake_rejects_files_over_configured_batch_limit(tmp_path: Path):
    path = tmp_path / "leads.csv"
    path.write_text("Legal Business Name,Website\nOne,https://one.example\nTwo,https://two.example\n", encoding="utf-8")
    with patch("scripts.orchestrator.enqueue_lead") as enqueue:
        with pytest.raises(ValueError, match="exceeds configured limit"):
            _enqueue_csv(path, "pilot", 3, max_rows=1)
        enqueue.assert_called_once()
