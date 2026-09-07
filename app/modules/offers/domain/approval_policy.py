from dataclasses import dataclass


@dataclass(frozen=True)
class ApprovalStep:
    number: int
    role: str


@dataclass(frozen=True)
class ApprovalPolicy:
    steps: tuple[ApprovalStep, ...]

    @classmethod
    def standard(cls) -> "ApprovalPolicy":
        return cls((ApprovalStep(1, "hiring_manager"), ApprovalStep(2, "tenant_admin")))

    def required_role(self, step: int) -> str:
        for approval_step in self.steps:
            if approval_step.number == step:
                return approval_step.role
        raise ValueError("Unknown approval step")
