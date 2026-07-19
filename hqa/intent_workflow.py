from __future__ import annotations

from typing import Any

from hqa.workflow_contract import (
    ContinueResearch,
    StartResearch,
    WorkflowReceipt,
)
from hqa.workflow_authority import WorkflowAuthorityError


class IntentWorkflowError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class IntentWorkflowCoordinator:
    """Crash-convergent seam between encrypted intent and research authorities."""

    def __init__(self, *, payload_store: Any, workflow_authority: Any) -> None:
        self.payload_store = payload_store
        self.workflow_authority = workflow_authority

    def accept_conversation(self, request: dict[str, Any]) -> dict[str, Any]:
        self._require_kind(request, "conversation_turn")
        payload = self.payload_store.put(request)
        return self._receipt(payload)

    def start_research(
        self,
        request: dict[str, Any],
        *,
        operation_id: str,
    ) -> dict[str, Any]:
        self._require_kind(request, "research_start")
        self._require_request_owner(request)
        payload = self.payload_store.put(request)
        self._require_authority_owner(payload)
        self._require_active_payload(payload)
        command = StartResearch(
            operation_id=operation_id,
            workspace_ref=payload["workspace_id"],
            managed_session_ref=payload["session_id"],
            payload_ref=payload["payload_ref"],
            intent_expires_at=payload["expires_at"],
        )
        workflow = self._apply_research(command)
        return self._bind_research(payload, workflow)

    def continue_research(
        self,
        request: dict[str, Any],
        *,
        operation_id: str,
        task_ref: str,
        expected_version: int,
    ) -> dict[str, Any]:
        self._require_kind(request, "research_continue")
        self._require_request_owner(request)
        payload = self.payload_store.put(request)
        self._require_authority_owner(payload)
        self._require_active_payload(payload)
        self._require_task_scope(payload, task_ref)
        command = ContinueResearch(
            operation_id=operation_id,
            task_ref=task_ref,
            expected_version=expected_version,
            payload_ref=payload["payload_ref"],
            intent_expires_at=payload["expires_at"],
        )
        workflow = self._apply_research(command)
        return self._bind_research(payload, workflow)

    def _bind_research(
        self,
        payload: dict[str, Any],
        workflow: WorkflowReceipt,
    ) -> dict[str, Any]:
        if workflow.attempt_ref is None:
            raise IntentWorkflowError("intent_workflow_attempt_missing")
        bound = self.payload_store.bind_consumer(
            payload_ref=payload["payload_ref"],
            consumer_ref=workflow.attempt_ref,
            owner_id=payload["owner_id"],
            workspace_id=payload["workspace_id"],
            session_id=payload["session_id"],
        )
        return self._receipt(bound, workflow=workflow)

    @staticmethod
    def _require_kind(request: Any, expected: str) -> None:
        if type(request) is not dict or request.get("kind") != expected:
            raise IntentWorkflowError("intent_workflow_kind_mismatch")

    def _require_authority_owner(self, payload: dict[str, Any]) -> None:
        if getattr(self.workflow_authority, "owner_user_id", None) != payload[
            "owner_id"
        ]:
            raise IntentWorkflowError("intent_workflow_owner_mismatch")

    def _require_request_owner(self, request: dict[str, Any]) -> None:
        if request.get("owner_id") != getattr(
            self.workflow_authority, "owner_user_id", None
        ):
            raise IntentWorkflowError("intent_workflow_owner_mismatch")

    def _require_active_payload(self, payload: dict[str, Any]) -> None:
        status = self.payload_store.status(
            payload["payload_ref"],
            owner_id=payload["owner_id"],
            workspace_id=payload["workspace_id"],
            session_id=payload["session_id"],
        )
        if status["status"] != "active":
            raise IntentWorkflowError("intent_workflow_payload_expired")

    def _apply_research(
        self, command: StartResearch | ContinueResearch
    ) -> WorkflowReceipt:
        try:
            return self.workflow_authority.apply(command)
        except WorkflowAuthorityError as exc:
            if exc.code in (
                "workflow_binding_conflict",
                "workflow_idempotency_conflict",
            ):
                raise IntentWorkflowError(
                    "intent_workflow_operation_conflict"
                ) from None
            raise

    def _require_task_scope(
        self, payload: dict[str, Any], task_ref: str
    ) -> None:
        snapshot = self.workflow_authority.snapshot(task_ref)
        if snapshot.owner_user_id != payload["owner_id"]:
            raise IntentWorkflowError("intent_workflow_owner_mismatch")
        if (
            snapshot.workspace_ref != payload["workspace_id"]
            or snapshot.managed_session_ref != payload["session_id"]
        ):
            raise IntentWorkflowError("intent_workflow_scope_mismatch")

    @staticmethod
    def _receipt(
        payload: dict[str, Any],
        *,
        workflow: WorkflowReceipt | None = None,
    ) -> dict[str, Any]:
        return {
            "schema_version": "2.0",
            "kind": payload["kind"],
            "payload_ref": payload["payload_ref"],
            "payload_digest": payload["payload_digest"],
            "expires_at": payload["expires_at"],
            "consumer_ref": payload["consumer_ref"],
            "task_ref": workflow.task_ref if workflow is not None else None,
            "attempt_ref": workflow.attempt_ref if workflow is not None else None,
            "workflow_event_id": workflow.event_id if workflow is not None else None,
            "task_version": workflow.task_version if workflow is not None else None,
            "workflow_replayed": workflow.replayed if workflow is not None else None,
        }


__all__ = ("IntentWorkflowCoordinator", "IntentWorkflowError")
