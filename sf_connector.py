from __future__ import annotations
import math
from typing import Callable
from simple_salesforce import Salesforce, SFType
import sf_config as cfg


class SalesforceConnector:
    def __init__(self) -> None:
        self._sf: Salesforce | None = None

    def connect(self) -> None:
        missing = [
            name for name, val in [
                ("SF_USERNAME", cfg.SF_USERNAME),
                ("SF_PASSWORD", cfg.SF_PASSWORD),
                ("SF_SECURITY_TOKEN", cfg.SF_SECURITY_TOKEN),
            ] if not val
        ]
        if missing:
            raise ValueError(f".env 파일에서 다음 항목을 채워주세요: {', '.join(missing)}")

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

    def insert_records(
        self,
        records: list[dict],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> tuple[int, int, list[str]]:
        if not self._sf:
            raise RuntimeError("Salesforce에 먼저 연결하세요.")

        sf_object: SFType = getattr(self._sf, cfg.SF_OBJECT_API_NAME)
        total = len(records)
        success_count = 0
        failure_count = 0
        errors: list[str] = []
        num_batches = math.ceil(total / cfg.SF_BATCH_SIZE)

        for batch_idx in range(num_batches):
            batch = records[batch_idx * cfg.SF_BATCH_SIZE:(batch_idx + 1) * cfg.SF_BATCH_SIZE]

            if len(batch) == 1:
                results = [sf_object.create(batch[0])]
            else:
                payload = [{"attributes": {"type": cfg.SF_OBJECT_API_NAME}, **rec} for rec in batch]
                response = self._sf._call_salesforce(
                    method="POST",
                    url=f"{self._sf.base_url}composite/sobjects",
                    json={"allOrNone": False, "records": payload},
                )
                results = response.json()

            for rec, result in zip(batch, results):
                if isinstance(result, dict) and result.get("success"):
                    success_count += 1
                else:
                    failure_count += 1
                    name = rec.get("Trainee_Name__c", "Unknown")
                    errs = result.get("errors", []) if isinstance(result, dict) else []
                    msg = errs[0].get("message", str(errs[0])) if errs else str(result)
                    errors.append(f"[{name}] {msg}")

            if on_progress:
                on_progress(min((batch_idx + 1) * cfg.SF_BATCH_SIZE, total), total)

        return success_count, failure_count, errors
