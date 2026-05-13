"""Advice writer uses session context and S3."""

from unittest.mock import MagicMock, patch

from src.session_context import session_id_ctx
from src.tools import advice as advice_mod


def test_record_run_advice_writes_s3(monkeypatch) -> None:
    monkeypatch.setenv("OUTPUT_BUCKET", "out-bucket")
    from src.settings import get_settings

    get_settings.cache_clear()
    put = MagicMock()
    mock_s3 = MagicMock()
    mock_s3.put_object = put

    tok = session_id_ctx.set("sess123")
    try:
        with patch.object(advice_mod, "get_client", return_value=mock_s3):
            out = advice_mod.record_run_advice(
                session_summary="s",
                what_worked="w",
                improvement_ideas="i",
            )
    finally:
        session_id_ctx.reset(tok)

    assert "wrote s3://out-bucket/" in out
    assert put.called
    kwargs = put.call_args.kwargs
    assert kwargs["Bucket"] == "out-bucket"
    assert "advice/raw/" in kwargs["Key"]
    assert "sess123" in kwargs["Key"]
