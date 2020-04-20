from typing import Tuple

import torch

from mantrap.agents.agent import Agent
from mantrap.utility.maths import Circle
from mantrap.utility.shaping import check_ego_action, check_ego_state


class IntegratorDTAgent(Agent):

    def dynamics(self, state: torch.Tensor, action: torch.Tensor, dt:  float) -> torch.Tensor:
        """
        .. math:: vel_{t+1} = action
        .. math:: pos_{t+1} = pos_t + vel_{t+1} * dt
        """
        assert check_ego_state(state, enforce_temporal=False)
        assert action.size() == torch.Size([2])

        velocity_new = action.float()
        position_new = (state[0:2] + velocity_new * dt).float()
        return self.build_state_vector(position_new, velocity_new)

    def inverse_dynamics(self, state: torch.Tensor, state_previous: torch.Tensor, dt: float) -> torch.Tensor:
        """
        .. math:: action = (pos_t - pos_{t-1}) / dt
        """
        assert check_ego_state(state, enforce_temporal=False)
        assert check_ego_state(state_previous, enforce_temporal=False)

        action = (state[0:2] - state_previous[0:2]) / dt
        assert check_ego_action(x=action)
        return action

    def control_limits(self) -> Tuple[float, float]:
        """
        .. math:: [- v_{max}, v_{max}]
        """
        return -self.speed_max, self.speed_max

    ###########################################################################
    # Reachability ############################################################
    ###########################################################################
    def reachability_boundary(self, time_steps: int, dt: float) -> Circle:
        """Single integrators can adapt their velocity instantly in any direction. Therefore the forward
        reachable set within the number of time_steps is just a circle (in general ellipse, but agent is
        assumed to be isotropic within this class, i.e. same control bounds for both x- and y-direction)
        around the current position, with radius being the maximal allowed agent speed.
        With `T = time_steps * dt` being the time horizon, the reachability bounds are determined for,
        the circle has the following parameters:

        .. math:: center = x(0)
        .. math:: radius = v_{max} * T

        :param time_steps: number of discrete time-steps in reachable time-horizon.
        :param dt: time interval which is assumed to be constant over full path sequence [s].
        """
        return Circle(center=self.position, radius=self.speed_max * dt * time_steps)
