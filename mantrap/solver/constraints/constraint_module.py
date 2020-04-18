from abc import ABC, abstractmethod
import logging
from typing import List, Tuple, Union

import numpy as np
import torch

from mantrap.utility.shaping import check_ego_trajectory


class ConstraintModule(ABC):
    """General constraint class.

    For an unified and general implementation of the constraint function modules this superclass implements methods
    for computing and logging the constraint value as well as the jacobian matrix simply based on a single method,
    the `_compute()` method, which has to be implemented in the child classes. `_compute()` returns the constraint value
    given a planned ego trajectory, while building a torch computation graph, which is used later on to determine the
    jacobian matrix using the PyTorch autograd library.

    :param horizon: planning time horizon in number of time-steps (>= 1).
    """
    def __init__(self, horizon: int, **module_kwargs):
        assert horizon >= 1
        self.T = horizon

        # Initialize module.
        self.initialize(**module_kwargs)

        # Logging variables for objective and gradient values. For logging the latest variables are stored
        # as class parameters and appended to the log when calling the `logging()` function, in order to avoid
        # appending multiple values within one optimization step.
        self._constraint_current = None

    @abstractmethod
    def initialize(self, **module_kwargs):
        raise NotImplementedError

    ###########################################################################
    # Constraint Formulation ##################################################
    ###########################################################################
    def constraint(self, ego_trajectory: torch.Tensor, ado_ids: List[str] = None) -> np.ndarray:
        """Determine constraint value for passed ego trajectory by calling the internal `compute()` method.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param ado_ids: ghost ids which should be taken into account for computation.
        """
        assert check_ego_trajectory(x=ego_trajectory, pos_and_vel_only=True, t_horizon=self.T + 1)
        constraint = self._compute(ego_trajectory, ado_ids=ado_ids)
        return self._return_constraint(constraint.detach().numpy())

    def jacobian(
        self,
        ego_trajectory: torch.Tensor,
        grad_wrt: torch.Tensor = None,
        ado_ids: List[str] = None
    ) -> np.ndarray:
        """Determine jacobian matrix for passed ego trajectory. Therefore determine the constraint values by
        calling the internal `compute()` method and en passant build a computation graph. Then using the pytorch
        autograd library compute the jacobian matrix through the previously built computation graph.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param grad_wrt: vector w.r.t. which the gradient should be determined.
        :param ado_ids: ghost ids which should be taken into account for computation.
        """
        assert check_ego_trajectory(x=ego_trajectory, pos_and_vel_only=True, t_horizon=self.T + 1)
        assert grad_wrt.requires_grad
        assert ego_trajectory.requires_grad  # otherwise constraints cannot have gradient function

        # Compute the constraint values and check whether a gradient between them and the ego_trajectory input (which
        # has been assured to require a gradient) exists, if the module-conditions for that are met.
        constraints = self._compute(ego_trajectory, ado_ids=ado_ids)
        if self._constraints_gradient_condition():
            assert constraints.requires_grad

        # In general the constraints might not be affected by the `ego_trajectory`, then they does not have
        # gradient function and the gradient is not defined. Then the jacobian is assumed to be zero.
        grad_size = int(grad_wrt.numel())
        jacobian = torch.zeros(constraints.numel() * grad_size)
        if constraints.requires_grad:
            for i, x in enumerate(constraints):
                grad = torch.autograd.grad(x, grad_wrt, retain_graph=True)
                jacobian[i * grad_size:(i + 1) * grad_size] = grad[0].flatten().detach()
        return jacobian.detach().numpy()

    @abstractmethod
    def _compute(self, ego_trajectory: torch.Tensor, ado_ids: List[str] = None) -> torch.Tensor:
        """Determine constraint value core method.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param ado_ids: ghost ids which should be taken into account for computation.
        """
        raise NotImplementedError

    @abstractmethod
    def _constraints_gradient_condition(self) -> bool:
        """Determine constraint violation based on the last constraint evaluation.

        The violation is the amount how much the solution state is inside the constraint active region.
        When the constraint is not active, then the violation is zero. The calculation is based on the last (cached)
        evaluation of the constraint function.
        """
        raise NotImplementedError

    ###########################################################################
    # Constraint Bounds #######################################################
    ###########################################################################
    @property
    def constraint_bounds(self) -> Tuple[Union[float, None], Union[float, None]]:
        """Lower and upper bounds for constraint values."""
        raise NotImplementedError

    def constraint_boundaries(self) -> Tuple[Union[np.ndarray, List[None]], Union[np.ndarray, List[None]]]:
        lower, upper = self.constraint_bounds
        lower = lower * np.ones(self.num_constraints) if lower is not None else [None] * self.num_constraints
        upper = upper * np.ones(self.num_constraints) if upper is not None else [None] * self.num_constraints
        return lower, upper

    ###########################################################################
    # Constraint Violation ####################################################
    ###########################################################################
    def compute_violation(self, ego_trajectory: torch.Tensor, ado_ids: List[str] = None) -> float:
        """Determine constraint violation based on some input ego trajectory and ado ids list.

        The violation is the amount how much the solution state is inside the constraint active region.
        When the constraint is not active, then the violation is zero. The calculation is based on the last (cached)
        evaluation of the constraint function.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param ado_ids: ghost ids which should be taken into account for computation.
        """
        assert check_ego_trajectory(x=ego_trajectory, pos_and_vel_only=True)
        constraint = self._compute(ego_trajectory, ado_ids=ado_ids)
        return self._violation(constraint=constraint.detach().numpy())

    def compute_violation_internal(self) -> float:
        """Determine constraint violation, i.e. how much the internal state is inside the constraint active region.
        When the constraint is not active, then the violation is zero. The calculation is based on the last (cached)
        evaluation of the constraint function.
        """
        return self._violation(constraint=self._constraint_current)

    def _violation(self, constraint: np.ndarray) -> float:
        num_constraints = constraint.size
        no_violation = np.zeros(num_constraints)
        lower, upper = self.constraint_bounds
        violation_lower = lower * np.ones(num_constraints) - constraint if lower is not None else no_violation
        violation_upper = constraint - upper * np.ones(num_constraints) if upper is not None else no_violation
        return float(np.sum(np.maximum(no_violation, violation_lower) + np.maximum(no_violation, violation_upper)))

    ###########################################################################
    # Utility #################################################################
    ###########################################################################
    def _return_constraint(self, constraint_value: np.ndarray) -> np.ndarray:
        self._constraint_current = constraint_value
        logging.debug(f"Module {self.__str__()} computed")
        return self._constraint_current

    ###########################################################################
    # Constraint Properties ###################################################
    ###########################################################################
    @property
    def inf_current(self) -> float:
        """Current infeasibility value (amount of constraint violation)."""
        return self.compute_violation_internal()

    @property
    def num_constraints(self) -> int:
        raise NotImplementedError  # should be absolute input-independent number for sanity checking
