from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts import generate_looplab_local_predictions as module


class LocalPredictionGenerationTests(unittest.TestCase):
    def test_dataset_requires_unique_ids_and_prompt(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "dataset.json"
            path.write_text(json.dumps([
                {"sample_id": "a", "prompt": "hello"},
                {"sample_id": "a", "prompt": "again"},
            ]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dataset_sample_schema_invalid"):
                module._read_dataset(path)

    def test_generates_one_prediction_per_sample(self):
        rows = [{"sample_id": "s1", "prompt": "p1", "system_prompt": "sys"}]
        client = MagicMock()
        client.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="answer"))
        ]
        result = module._generate(client, "local-model", rows, 128)
        self.assertEqual(result, [{"sample_id": "s1", "output": "answer"}])
        client.chat.completions.create.assert_called_once()
        kwargs = client.chat.completions.create.call_args.kwargs
        self.assertEqual(kwargs["temperature"], 0.0)
        self.assertIs(kwargs["include_reasoning"], False)

    def test_output_paths_cannot_alias_each_other_or_input(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "dataset.json"
            source.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "output_paths_must_be_distinct_from_inputs"):
                module._ensure_distinct_outputs([source, Path(temp) / "out.json"], [source])
            with self.assertRaisesRegex(ValueError, "output_paths_must_be_distinct_from_inputs"):
                module._ensure_distinct_outputs([Path(temp) / "same.json", Path(temp) / "same.json"], [source])


if __name__ == "__main__":
    unittest.main()
