"""Plan aggregate: the full validated input set (`03-data-model.md`, `06-code-structure-and-dependencies.md`).

Cross-table checks mirror `02-architecture.md`'s "Control flow: a solve run", step 2:
reporting every schema error beats reporting one infeasibility.
"""

from pydantic import BaseModel, model_validator

from .allocation import AllocationRow
from .bounds import Bounds
from .calendar import Month
from .capacity import Capacity
from .people import Person
from .projects import Project, RateStructure
from .rates import Rate, WrapRate
from .targets import Target


class Plan(BaseModel):
    horizon_start: Month
    horizon_end: Month
    people: list[Person]
    projects: list[Project]
    rate_structures: list[RateStructure]
    rates: list[Rate]
    wrap_rates: list[WrapRate]
    capacity: list[Capacity]
    bounds: list[Bounds]
    targets: list[Target]
    allocation: list[AllocationRow] = []
    closed_through: Month | None = None
    """Months <= this are closed: actuals are final, `F` fixes their cells to `hours_actual`."""

    def horizon(self) -> list[Month]:
        return Month.range(self.horizon_start, self.horizon_end)

    def person(self, person_id: str) -> Person:
        return self._person_index[person_id]

    def project(self, project_id: str) -> Project:
        return self._project_index[project_id]

    def rate_structure(self, structure_id: str) -> RateStructure:
        return self._structure_index[structure_id]

    def rate(self, person_id: str, month: Month) -> Rate:
        return self._rate_index[(person_id, month)]

    def wrap_rate(self, month: Month) -> WrapRate:
        return self._wrap_index[month]

    def capacity_of(self, person_id: str, month: Month) -> Capacity:
        return self._capacity_index[(person_id, month)]

    def model_post_init(self, __context: object) -> None:
        self._person_index = {p.person_id: p for p in self.people}
        self._project_index = {p.project_id: p for p in self.projects}
        self._structure_index = {rs.structure_id: rs for rs in self.rate_structures}
        self._rate_index = {(r.person_id, r.month): r for r in self.rates}
        self._wrap_index = {wr.month: wr for wr in self.wrap_rates}
        self._capacity_index = {(c.person_id, c.month): c for c in self.capacity}

    @model_validator(mode="after")
    def _cross_validate(self) -> "Plan":
        errors: list[str] = []
        person_ids = {p.person_id for p in self.people}
        project_ids = {p.project_id for p in self.projects}
        structure_ids = {rs.structure_id for rs in self.rate_structures}
        months = self.horizon()
        month_set = set(months)

        for b in self.bounds:
            if b.person_id not in person_ids:
                errors.append(f"bounds row references unknown person {b.person_id}")
            if b.project_id not in project_ids:
                errors.append(f"bounds row references unknown project {b.project_id}")

        for proj in self.projects:
            if proj.rate_structure not in structure_ids:
                errors.append(
                    f"project {proj.project_id} references unknown rate_structure {proj.rate_structure}"
                )

        rate_index = {(r.person_id, r.month) for r in self.rates}
        capacity_index = {(c.person_id, c.month) for c in self.capacity}
        for person in self.people:
            for m in months:
                if not person.is_active(m):
                    continue
                if (person.person_id, m) not in rate_index:
                    errors.append(f"missing rates row for {person.person_id} in {m}")
                if (person.person_id, m) not in capacity_index:
                    errors.append(f"missing capacity row for {person.person_id} in {m}")

        wrap_months = {wr.month for wr in self.wrap_rates}
        for m in month_set:
            if m not in wrap_months:
                errors.append(f"missing wrap_rates row for {m}")

        project_by_id = {p.project_id: p for p in self.projects}
        for t in self.targets:
            proj = project_by_id.get(t.project_id)
            if proj is None:
                errors.append(f"target references unknown project {t.project_id}")
            elif not (proj.pop_start <= t.month <= proj.pop_end):
                errors.append(
                    f"target for {t.project_id} in {t.month} falls outside its PoP "
                    f"[{proj.pop_start}, {proj.pop_end}]"
                )

        if errors:
            raise ValueError("Plan validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
        return self
