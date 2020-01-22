from abc import abstractmethod
import logging
import random
import string

import numpy as np

from mantrap.constants import agent_speed_max, sim_dt_default
from mantrap.utility.shaping import check_state


class Agent:
    def __init__(
        self,
        position: np.ndarray,
        velocity: np.ndarray,
        time: float = 0,
        history: np.ndarray = None,
        identifier: str = None,
        log: bool = True,
        **kwargs,
    ):
        assert position.size == 2, "position must be two-dimensional (x, y)"
        assert velocity.size == 2, "velocity must be two-dimensional (vx, vy)"
        assert time >= 0, "time must be larger or equal to zero"

        self._position = position
        self._velocity = velocity

        # Initialize (and/or append) history vector.
        if history is not None:
            assert history.shape[1] == 6, "history should contain 2D stamped pose & velocity (x, y, theta, vx, vy, t)"
            self._history = history
            self._history = np.vstack((self._history, np.hstack((self.state, time))))
        else:
            self._history = np.reshape(np.hstack((self.state, time)), (1, 6))

        # Create random agent color (reddish), for evaluation only.
        self._color = np.random.uniform(0.0, 0.8, size=3)
        # Random identifier.
        letters = string.ascii_lowercase
        self._id = identifier if identifier is not None else "".join(random.choice(letters) for _ in range(3))
        if log:
            logging.info(f"agent [{self._id}]: position={self.position}, velocity={self.velocity}, color={self._color}")

    def update(self, action: np.ndarray, dt: float = sim_dt_default):
        """Update internal state (position, velocity and history) by executing some action for time dt."""
        assert dt > 0.0, "time-step must be larger than 0"
        state_new = self.dynamics(self.state, action, dt=dt)
        self._position = state_new[0:2]
        self._velocity = state_new[3:5]

        # maximal speed constraint.
        if self.speed > agent_speed_max:
            logging.error(f"agent {self.id} has surpassed maximal speed, with {self.speed} > {agent_speed_max}")
            assert not np.isinf(self.speed), "speed is infinite, physical break"
            self._velocity = self._velocity / self.speed * agent_speed_max

        # append history with new state.
        self._history = np.vstack((self._history, np.hstack((self.state, self._history[-1, -1] + dt))))

    def unroll_trajectory(self, policy: np.ndarray, dt: float = sim_dt_default) -> np.ndarray:
        """Build the trajectory from some policy and current state, by iteratively applying the model dynamics.
        Thereby a perfect model i.e. without uncertainty and correct is assumed.

        :param policy: sequence of inputs to apply to the robot (N, input_size).
        :param dt: time interval [s].
        :return: resulting trajectory (no uncertainty in dynamics assumption !), (N, 4).
        """
        assert dt > 0.0, "time-step must be larger than 0"
        if len(policy.shape) == 1:  # singe action as policy
            policy = np.expand_dims(policy, axis=0)

        # initial trajectory point is the current state.
        trajectory = np.zeros((policy.shape[0] + 1, 6))
        trajectory[0, :] = np.hstack((self.state, 0))

        # every next state follows from robot's dynamics recursion, basically assuming no model uncertainty.
        state_at_t = self.state.copy()
        for k in range(policy.shape[0]):
            state_at_t = self.dynamics(state_at_t, action=policy[k, :], dt=dt)
            trajectory[k + 1, :] = np.hstack((state_at_t, (k + 1) * dt))
        return trajectory

    def reset(self, state: np.ndarray, history: np.ndarray = None):
        """Reset the complete state of the agent by resetting its position and velocity. Either adapt the agent's
        history to the new state (i.e. append it to the already existing history) if history is given as None or set
        it to some given trajectory.
        """
        assert check_state(state, enforce_temporal=True), "state has to be at least 5-dimensional"
        if history is None:
            history = np.vstack((self._history, state))
        self._position = state[0:2]
        self._velocity = state[3:5]
        self._history = history

    @abstractmethod
    def dynamics(self, state: np.ndarray, action: np.ndarray, dt: float = sim_dt_default):
        """Forward integrate the egos motion given some state-action pair and an integration time-step. Since every
        ego agent type has different dynamics (like single-integrator or Dubins Car) this method is implemented
        abstractly.
        """
        pass

    ###########################################################################
    # State properties ########################################################
    ###########################################################################

    @property
    def state(self) -> np.ndarray:
        return np.hstack((self.pose, self.velocity))

    @property
    def position(self) -> np.ndarray:
        return self._position

    @property
    def pose(self) -> np.ndarray:
        return np.array([self._position[0], self._position[1], np.arctan2(self._velocity[1], self._velocity[0])])

    @property
    def velocity(self) -> np.ndarray:
        return self._velocity

    @property
    def speed(self) -> float:
        return np.linalg.norm(self._velocity)

    ###########################################################################
    # Dimensions ##############################################################
    ###########################################################################

    @property
    def length_state(self) -> int:
        return 5  # (x, y, theta, vx, vy)

    @property
    def length_action(self) -> int:
        return 2  # override if necessary (!)

    ###########################################################################
    # History properties ######################################################
    ###########################################################################

    @property
    def history(self) -> np.ndarray:
        return self._history

    ###########################################################################
    # Visualization/Utility properties ########################################
    ###########################################################################

    @property
    def color(self) -> np.ndarray:
        return self._color

    @property
    def id(self) -> str:
        return self._id