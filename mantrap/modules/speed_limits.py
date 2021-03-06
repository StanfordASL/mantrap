import typing

import numpy as np
import torch

import mantrap.utility.maths
import mantrap.utility.shaping

from .base import PureConstraintModule


class SpeedLimitModule(PureConstraintModule):
    """Maximal robot speed at every point in time.

    For computing this constraint simply the norm of the velocity stored in the trajectory itself is determined
    and compared to the maximal agent's speed limit. For 0 < t < T_{planning}:

    .. math:: v_{min} <= v(t) < v_{max}

    These are many constraints, 2 * T_{planning} to be exact. However all of them are linear, and therefore
    easy to use within the optimisation as well as efficient to compute.
    """
    def __init__(self, env: mantrap.environment.base.GraphBasedEnvironment, t_horizon: int, **unused):
        super(SpeedLimitModule, self).__init__(env=env, t_horizon=t_horizon)

    def _constraint_core(self, ego_trajectory: torch.Tensor, ado_ids: typing.List[str], tag: str
                         ) -> typing.Union[torch.Tensor, None]:
        """Determine constraint value core method.

        The max speed constraints simply are computed by extracting the velocities over the full ego trajectory.

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param ado_ids: ghost ids which should be taken into account for computation.
        :param tag: name of optimization call (name of the core).
        """
        velocities = ego_trajectory[:, 2:4].flatten().float()
        return velocities

    def compute_jacobian_analytically(
        self, ego_trajectory: torch.Tensor, grad_wrt: torch.Tensor, ado_ids: typing.List[str], tag: str
    ) -> typing.Union[np.ndarray, None]:
        """Compute Jacobian matrix analytically.

        While the Jacobian matrix of the constraint can be computed automatically using PyTorch's automatic
        differentiation package there might be an analytic solution, which is when known for sure more
        efficient to compute. Although it is against the convention to use torch representations whenever
        possible, this function returns numpy arrays, since the main jacobian() function has to return
        a numpy array. Hence, not computing based on numpy arrays would just introduce an un-necessary
        `.detach().numpy()`.

        When the gradient shall be computed with respect to the controls, then computing the gradient
        analytically is very straight-forward, by just applying the chain rule.

        .. math::\\grad g(x) = \\frac{dg(x)}{dz} = \\frac{dg(x)}{dx} \\frac{dx}{du}

        :param ego_trajectory: planned ego trajectory (t_horizon, 5).
        :param grad_wrt: vector w.r.t. which the gradient should be determined.
        :param ado_ids: ghost ids which should be taken into account for computation.
        :param tag: name of optimization call (name of the core).
        """
        assert mantrap.utility.shaping.check_ego_trajectory(ego_trajectory)

        with torch.no_grad():

            # Compute controls from trajectory, assuming that the `grad_wrt` are the controls.
            # However not explicitly checked here, for computational reasons and as following
            # the general formulation in this project.
            ego_controls = self._env.ego.roll_trajectory(ego_trajectory, dt=self._env.dt)

            # Otherwise compute Jacobian using formula in method's description above.
            t_horizon, _ = ego_controls.shape
            _, x_size = ego_trajectory.shape
            assert t_horizon == self.t_horizon  # jacobian_structure
            assert x_size == 5  # jacobian_structure

            dx_du = self._env.ego.dx_du(ego_controls, dt=self._env.dt).detach().numpy()
            dg_dx = np.zeros((2 * (t_horizon + 1), (t_horizon + 1) * x_size))
            for t in range(t_horizon + 1):
                for k in range(2):
                    dg_dx[2 * t + k, t * x_size + 2 + k] = 1
            return np.matmul(dg_dx, dx_du).flatten()

    def normalize(self, x: typing.Union[np.ndarray, float]) -> typing.Union[np.ndarray, float]:
        """Normalize the objective/constraint value for improved optimization performance.

        Compute the normalize factor as the maximally allowed velocity of the robot, that is stored as a
        property of it in the environment representation itself. Thereby, we intrinsically assume that the speed
        limits are identical in both direction, which we assert before.

        :param x: objective/constraint value in normal value range.
        :returns: normalized objective/constraint value in range [-1, 1].
        """
        v_min, v_max = self._env.ego.speed_limits
        assert np.isclose(abs(v_min), abs(v_max))
        return x / v_max

    def gradient_condition(self) -> bool:
        """Condition for back-propagating through the objective/constraint in order to obtain the
        objective's gradient vector/jacobian (numerically). If returns True and the ego_trajectory
        itself requires a gradient, the objective/constraint value, stored from the last computation
        (`_current_`-variables) has to require a gradient as well.

        Since the velocities are part of the given ego_trajectory, the gradient should always exist.
        """
        return True

    ###########################################################################
    # Constraint Bounds #######################################################
    ###########################################################################
    def _constraint_limits(self) -> typing.Tuple[typing.Union[float, None], typing.Union[float, None]]:
        """Lower and upper bounds for constraint values.

        The speed boundaries are a property of the robot agent.
        """
        return self.env.ego.speed_limits

    def _num_constraints(self, ado_ids: typing.List[str]) -> int:
        return 2 * (self.t_horizon + 1)  # trajectory has length t_horizon + 1 !

    ###########################################################################
    # Constraint Properties ###################################################
    ###########################################################################
    @property
    def name(self) -> str:
        return "speed_limits"
