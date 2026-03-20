"""Salesforce connection and data upload handler.

Uses simple-salesforce with Username + Password + Security Token authentication.
"""

from __future__ import annotations

import math
from typing import Callable

from simple_salesforce import Salesforce, SFType

import sf_config as cfg


class SalesforceConnector:
    """Manages a Salesforce session and record insertion."""

    def __init__(self) -> None:
        self._sf: Salesforce | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Authenticate with Salesforce via Username + Password + Security Token.

        Raises:
            ValueError: If required credentials are missing from .env.
        """
        missing = [
            name
            for name, val in [
                ("SF_USERNAME", cfg.SF_USERNAME),
                ("SF_PASSWORD", cfg.SF_PASSWORD),
                ("SF_SECURITY_TOKEN", cfg.SF_SECURITY_TOKEN),
            ]
            if not val
        ]
        if missing:
            raise ValueError(
                f".env 파일에서 다음 항목을 채워주세요: {', '.join(missing)}"
            )

        self._sf = Salesforce(
            username=cfg.SF_USERNAME,
            password=cfg.SF_PASSWORD,
            security_token=cfg.SF_SECURITY_TOKEN,
            domain=cfg.SF_DOMAIN,
        )

    def disconnect(self) -> None:
        self._sf = None

    @property
    def is_connected(self) -> bool:
        return self._sf is not None

    # ------------------------------------------------------------------
    # Insert
    # ------------------------------------------------------------------

    def insert_records(
        self,
        records: list[dict],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int, list[str]]:
        """Insert records into the configured Salesforce Custom Object.

        Args:
            records:     List of dicts with SF field API names as keys.
            on_progress: Optional callback(uploaded_count, total_count).

        Returns:
            Tuple of (success_count, failure_count, error_messages).
        """
        if not self._sf:
            raise RuntimeError("Salesforce에 먼저 연결하세요.")

        sf_object: SFType = getattr(self._sf, cfg.SF_OBJECT_API_NAME)

        total = len(records)
        success_count = 0
        failure_count = 0
        errors: list[str] = []

        batch_size = cfg.SF_BATCH_SIZE
        num_batches = math.ceil(total / batch_size)

        for batch_idx in range(num_batches):
            batch = records[batch_idx * batch_size : (batch_idx + 1) * batch_size]

            # simple-salesforce bulk API  (collections insert)
            results = sf_object.create(batch) if len(batch) == 1 else None

            if results is None:
                # Use bulk for multi-record batches
                results = self._bulk_insert(sf_object, batch)
            else:
                # Single record: wrap result in list
                results = [results]

            for rec, result in zip(batch, results):
                if isinstance(result, dict) and result.get("success"):
                    success_count += 1
                else:
                    failure_count += 1
                    error_msg = self._extract_error(result, rec)
                    errors.append(error_msg)

            if on_progress:
                on_progress(min((batch_idx + 1) * batch_size, total), total)

        return success_count, failure_count, errors

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bulk_insert(self, sf_object: SFType, batch: list[dict]) -> list[dict]:
        """Insert multiple records using Salesforce Collections API."""
        payload = [{"attributes": {"type": cfg.SF_OBJECT_API_NAME}, **rec} for rec in batch]
        response = self._sf._call_salesforce(  # type: ignore[union-attr]
            method="POST",
            url=f"{self._sf.base_url}composite/sobjects",  # type: ignore[union-attr]
            json={"allOrNone": False, "records": payload},
        )
        return response.json()

    @staticmethod
    def _extract_error(result: object, record: dict) -> str:
        name = record.get("Trainee_Name__c", "Unknown")
        if isinstance(result, dict):
            errs = result.get("errors", [])
            if errs:
                return f"[{name}] {errs[0].get('message', str(errs[0]))}"
        return f"[{name}] 알 수 없는 오류: {result}"
