from typing import Any
from cls.enumeration import enumerate_terms, interpret_term
from cls.fcl import FiniteCombinatoryLogic
from cls.types import (
    Arrow,
    Constructor,
    Literal,
    Param,
    TVar,
    Type,
    Product,
    Intersection,
)


def motorcount():
    pass


def robotarm():
    def c(x: Type[str]) -> Type[str]:
        return Constructor("c", x)

    class Part:
        def __init__(self, name: str):
            self.name = name

        def __call__(self, *collect) -> Any:
            return (self.name + " params: " + str(collect)).replace("\\", "")

    repo = {
        Part("motor"): Param(
            "current_motor_count",
            int,
            lambda _: True,
            Param(
                "new_motor_count",
                int,
                lambda vars: vars["current_motor_count"].value + 1
                == vars["new_motor_count"].value,
                Intersection(
                    Arrow(Constructor("Structural"), Constructor("Motor")),
                    Arrow(c(TVar("current_motor_count")), c(TVar("new_motor_count"))),
                ),
            ),
        ),
        Part("Link"): Param(
            "current_motor_count",
            int,
            lambda _: True,
            Intersection(
                Arrow(Constructor("Motor"), Constructor("Structural")),
                Arrow(c(TVar("current_motor_count")), c(TVar("current_motor_count"))),
            ),
        ),
        Part("ShortLink"): Param(
            "current_motor_count",
            int,
            lambda _: True,
            Intersection(
                Arrow(Constructor("Motor"), Constructor("Structural")),
                Arrow(c(TVar("current_motor_count")), c(TVar("current_motor_count"))),
            ),
        ),
        Part("Effector"): Intersection(Constructor("Structural"), c(Literal(0, int))),
        Part("Base"): Param(
            "current_motor_count",
            int,
            lambda _: True,
            Intersection(
                Arrow(Constructor("Motor"), Constructor("Base")),
                Arrow(c(TVar("current_motor_count")), c(TVar("current_motor_count"))),
            ),
        ),
    }

    literals = {int: list(range(10))}

    fcl: FiniteCombinatoryLogic[str, Any] = FiniteCombinatoryLogic(
        repo, literals=literals
    )
    query = Intersection(Constructor("Base"), c(Literal(3, int)))
    grammar = fcl.inhabit(query)
    # print(grammar.show())

    for term in enumerate_terms(query, grammar):
        print(interpret_term(term))


if __name__ == "__main__":
    robotarm()