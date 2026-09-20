from __future__ import annotations


class ApprovalRequired(RuntimeError):
    def __init__(
        self,
        task_id: str,
        description: str,
    ) -> None:
        self.task_id = task_id
        self.description = description

        super().__init__(
            f"Human approval required for {task_id}: {description}"
        )
