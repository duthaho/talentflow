from app.modules.onboarding.domain.policy import TransientStepError


class FaultInjectingHris:
    def __init__(self, inner, faults):
        self.inner, self.faults = inner, faults

    async def upsert_employee(self, key, person):
        if "create_employee" in self.faults:
            raise TransientStepError()
        return await self.inner.upsert_employee(key, person)

    async def delete_employee(self, key):
        return await self.inner.delete_employee(key)


class FaultInjectingDirectory:
    def __init__(self, inner, faults):
        self.inner, self.faults = inner, faults

    async def provision_user(self, case, saga, person):
        if "provision_account" in self.faults:
            raise TransientStepError()
        return await self.inner.provision_user(case, saga, person)

    async def delete_user(self, case, saga):
        return await self.inner.delete_user(case, saga)
