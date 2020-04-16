import pytest
import torch

from mantrap.agents.agent import Agent
from mantrap.agents import AGENTS, IntegratorDTAgent, DoubleIntegratorDTAgent


###########################################################################
# Tests - All Agents ######################################################
###########################################################################
@pytest.mark.parametrize("agent_class", AGENTS)
class TestAgent:

    @staticmethod
    def test_dynamics(agent_class: Agent.__class__):
        control = torch.rand(2)
        agent = agent_class(position=torch.rand(2), velocity=torch.rand(2))
        state_next = agent.dynamics(state=agent.state, action=control, dt=1.0)
        control_output = agent.inverse_dynamics(state_previous=agent.state, state=state_next, dt=1.0)
        assert torch.all(torch.isclose(control, control_output))

    @staticmethod
    def test_history(agent_class: Agent.__class__):
        agent = agent_class(position=torch.tensor([-1, 4]), velocity=torch.ones(2))
        for _ in range(4):
            agent.update(action=torch.ones(2), dt=1.0)
        assert len(agent.history.shape) == 2
        assert agent.history.shape[0] == 5
        assert agent.history.shape[1] == 5

    @staticmethod
    def test_reset(agent_class: Agent.__class__):
        agent = agent_class(torch.tensor([5, 6]))
        agent.reset(state=torch.tensor([1, 5, 4, 2, 1.0]), history=None)
        assert torch.all(torch.eq(agent.position, torch.tensor([1, 5]).float()))
        assert torch.all(torch.eq(agent.velocity, torch.tensor([4, 2]).float()))

    @staticmethod
    def test_rolling(agent_class: Agent.__class__):
        agent = agent_class(position=torch.zeros(2))
        controls = torch.tensor([[1, 1], [2, 2], [4, 4]]).float()
        trajectory = agent.unroll_trajectory(controls, dt=1.0)
        assert torch.all(torch.isclose(controls, agent.roll_trajectory(trajectory, dt=1.0)))

    @staticmethod
    def test_initialization(agent_class: Agent.__class__):
        # history initial value = None.
        agent = agent_class(position=torch.zeros(2), velocity=torch.zeros(2), history=None)
        assert torch.all(torch.eq(agent.history, torch.zeros((1, 5))))

        # history initial value != None
        history = torch.tensor([5, 6, 0, 0, -1]).view(1, 5).float()
        history_exp = torch.tensor([[5, 6, 0, 0, -1],
                                    [1, 1, 0, 0, 0]]).float()
        agent = agent_class(position=torch.ones(2), velocity=torch.zeros(2), history=history)
        assert torch.all(torch.eq(agent.history, history_exp))

    @staticmethod
    def test_update(agent_class: Agent.__class__):
        """Test agent `update()` using the `dynamics()` which has been tested independently so is fairly safe
        to use for testing since it grants generality over agent types. """
        state_init = torch.rand(4)
        control_input = torch.rand(2)
        agent = agent_class(position=state_init[0:2], velocity=state_init[2:4])
        state_next = agent.dynamics(state=agent.state, action=control_input, dt=1.0)
        agent.update(control_input, dt=1.0)

        assert torch.all(torch.eq(agent.position, state_next[0:2]))
        assert torch.all(torch.eq(agent.velocity, state_next[2:4]))
        assert torch.all(torch.eq(agent.history[0, 0:4], state_init))
        assert torch.all(torch.eq(agent.history[1, 0:4], state_next))


###########################################################################
# Test - Single Integrator ################################################
###########################################################################
@pytest.mark.parametrize(
    "position, velocity, control, position_expected, velocity_expected",
    [
        (torch.tensor([1, 0]), torch.zeros(2), torch.zeros(2), torch.tensor([1, 0]), torch.zeros(2)),
        (torch.tensor([1, 0]), torch.tensor([2, 3]), torch.zeros(2), torch.tensor([1, 0]), torch.tensor([0, 0])),
        (torch.tensor([1, 0]), torch.zeros(2), torch.tensor([2, 3]), torch.tensor([3, 3]), torch.tensor([2, 3])),
    ],
)
def test_dynamics_single_integrator(
    position: torch.Tensor,
    velocity: torch.Tensor,
    control: torch.Tensor,
    position_expected: torch.Tensor,
    velocity_expected: torch.Tensor,
):
    agent = IntegratorDTAgent(position=position, velocity=velocity)
    state_next = agent.dynamics(state=agent.state, action=control, dt=1.0)
    assert torch.all(torch.isclose(state_next[0:2], position_expected.float()))
    assert torch.all(torch.isclose(state_next[2:4], velocity_expected.float()))


@pytest.mark.parametrize(
    "position, velocity, state_previous, control_expected",
    [
        (torch.tensor([1, 0]), torch.zeros(2), torch.zeros(5), torch.tensor([1, 0])),
        (torch.tensor([1, 0]), torch.tensor([2, 3]), torch.zeros(5), torch.tensor([1, 0])),
        (torch.tensor([1, 0]), torch.zeros(2), torch.tensor([2, 0, 0, 0, -1.0]), torch.tensor([-1, 0])),
    ],
)
def test_inv_dynamics_single_integrator(
    position: torch.Tensor,
    velocity: torch.Tensor,
    state_previous: torch.Tensor,
    control_expected: torch.Tensor,
):
    agent = IntegratorDTAgent(position=position, velocity=velocity)
    control = agent.inverse_dynamics(state=agent.state, state_previous=state_previous, dt=1.0)
    assert torch.all(torch.isclose(control, control_expected.float()))


@pytest.mark.parametrize("position, velocity, dt, n", [(torch.tensor([-5.0, 0.0]), torch.tensor([1.0, 0.0]), 1, 10)])
def test_unrolling(position: torch.Tensor, velocity: torch.Tensor, dt: float, n: int):
    ego = IntegratorDTAgent(position=position, velocity=velocity)
    policy = torch.stack((torch.ones(n) * velocity[0], torch.ones(n) * velocity[1])).T
    ego_trajectory = ego.unroll_trajectory(controls=policy, dt=dt)

    ego_trajectory_x_exp = torch.linspace(position[0].item(), position[0].item() + velocity[0].item() * n * dt, n + 1)
    ego_trajectory_y_exp = torch.linspace(position[1].item(), position[1].item() + velocity[1].item() * n * dt, n + 1)
    assert torch.all(torch.eq(ego_trajectory[:, 0], ego_trajectory_x_exp))
    assert torch.all(torch.eq(ego_trajectory[:, 1], ego_trajectory_y_exp))
    assert torch.all(torch.eq(ego_trajectory[:, 2], torch.ones(n + 1) * velocity[0]))
    assert torch.all(torch.eq(ego_trajectory[:, 3], torch.ones(n + 1) * velocity[1]))
    assert torch.all(torch.eq(ego_trajectory[:, 4], torch.linspace(0, n, n + 1)))


###########################################################################
# Test - Double Integrator ################################################
###########################################################################
@pytest.mark.parametrize(
    "position, velocity, control, position_expected, velocity_expected",
    [
        (torch.tensor([1, 0]), torch.zeros(2), torch.zeros(2), torch.tensor([1, 0]), torch.zeros(2)),
        (torch.tensor([1, 0]), torch.tensor([2, 3]), torch.zeros(2), torch.tensor([3, 3]), torch.tensor([2, 3])),
        (torch.tensor([1, 0]), torch.zeros(2), torch.tensor([2, 3]), torch.tensor([2, 1.5]), torch.tensor([2, 3])),
    ],
)
def test_dynamics_double_integrator(
    position: torch.Tensor,
    velocity: torch.Tensor,
    control: torch.Tensor,
    position_expected: torch.Tensor,
    velocity_expected: torch.Tensor,
):
    agent = DoubleIntegratorDTAgent(position=position, velocity=velocity)
    state_next = agent.dynamics(state=agent.state, action=control, dt=1.0)
    assert torch.all(torch.isclose(state_next[0:2], position_expected.float()))
    assert torch.all(torch.isclose(state_next[2:4], velocity_expected.float()))


@pytest.mark.parametrize(
    "position, velocity, state_previous, control_expected",
    [
        (torch.tensor([1, 0]), torch.zeros(2), torch.zeros(5), torch.tensor([1, 0])),
        (torch.tensor([1, 0]), torch.tensor([2, 3]), torch.zeros(5), torch.tensor([1, 0])),
        (torch.tensor([1, 0]), torch.zeros(2), torch.tensor([2, 0, 0, 0, -1.0]), torch.tensor([-1, 0])),
    ],
)
def test_inv_dynamics_double_integrator(
    position: torch.Tensor,
    velocity: torch.Tensor,
    state_previous: torch.Tensor,
    control_expected: torch.Tensor,
):
    agent = IntegratorDTAgent(position=position, velocity=velocity)
    control = agent.inverse_dynamics(state=agent.state, state_previous=state_previous, dt=1.0)
    assert torch.all(torch.isclose(control, control_expected.float()))
