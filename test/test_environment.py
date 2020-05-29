from collections import namedtuple

import numpy as np
import pytest
import torch

import mantrap.agents
import mantrap.constants
import mantrap.environment
import mantrap.utility.maths
import mantrap.utility.shaping


###########################################################################
# Tests - All Environment #################################################
###########################################################################
@pytest.mark.parametrize("environment_class", [mantrap.environment.KalmanEnvironment,
                                               mantrap.environment.PotentialFieldEnvironment,
                                               mantrap.environment.SocialForcesEnvironment,
                                               mantrap.environment.ORCAEnvironment,
                                               mantrap.environment.Trajectron])
@pytest.mark.parametrize("num_modes", [1, 2, 5])
class TestEnvironment:

    @staticmethod
    def test_initialization(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__,
                            num_modes: int):
        ego_position = torch.rand(2).float()
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_position)
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()

        assert torch.all(torch.eq(env.ego.position, ego_position))
        assert env.num_ados == 0
        assert env.time == 0.0
        env.add_ado(position=torch.tensor([6, 7]), velocity=torch.ones(2), num_modes=num_modes)

        assert torch.all(torch.eq(env.ghosts[0].agent.position, torch.tensor([6, 7]).float()))
        assert torch.all(torch.eq(env.ghosts[0].agent.velocity, torch.ones(2)))

    @staticmethod
    def test_step(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__, num_modes: int):
        ado_init_position = torch.zeros(2)
        ado_init_velocity = torch.ones(2)
        ego_init_position = torch.tensor([-4, 6])
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_init_position)

        # In order to be able to verify the generated trajectories easily, we assume uni-modality here.
        env.add_ado(position=ado_init_position, velocity=ado_init_velocity, num_modes=1)
        assert env.num_ados == 1
        assert env.num_modes == 1
        assert env.num_ghosts == 1

        t_horizon = 5
        ego_controls = torch.stack([torch.tensor([1, 0])] * t_horizon)
        ego_trajectory = env.ego.unroll_trajectory(controls=ego_controls, dt=env.dt)
        for t in range(t_horizon):
            ado_t, ego_t = env.step(ego_action=ego_controls[t])

            # Check dimensions of outputted ado and ego states.
            assert ado_t.numel() == 5
            assert ado_t.shape == (1, 5)
            assert ego_t.numel() == 5

            # While the exact value of the ado agent's states depends on the environment dynamics used, all of them
            # are based on the ego state (control), which is thought to be enforced while forwarding the environment.
            assert all(torch.isclose(ego_t, ego_trajectory[t+1, :]))

    @staticmethod
    def test_step_reset(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__, num_modes: int):
        ego_position = torch.rand(2)
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_position)

        # In order to be able to verify the generated trajectories easily, we assume uni-modality here.
        env.add_ado(position=torch.zeros(2), velocity=torch.zeros(2), num_modes=1)
        env.add_ado(position=torch.ones(2), velocity=torch.zeros(2), num_modes=1)

        ego_next_state = torch.rand(5)
        ado_next_states = torch.rand(env.num_ados, 5)
        env.step_reset(ego_state_next=ego_next_state, ado_states_next=ado_next_states)

        assert torch.all(torch.eq(env.ego.state_with_time, ego_next_state))
        for i in range(env.num_ghosts):
            assert torch.all(torch.eq(env.ghosts[i].agent.state_with_time, ado_next_states[i]))

    @staticmethod
    def test_prediction_trajectories_shape(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__,
                                           num_modes: int):
        env = environment_class()
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()

        t_horizon = 4
        history = torch.stack(5 * [torch.tensor([1, 0, 0, 0, 0])])
        env.add_ado(goal=torch.ones(2), position=torch.tensor([-1, 0]), num_modes=num_modes, history=history)
        env.add_ado(goal=torch.zeros(2), position=torch.tensor([1, 0]), num_modes=num_modes, history=history)

        ado_trajectories = env.predict_wo_ego(t_horizon=t_horizon)
        assert mantrap.utility.shaping.check_ado_trajectories(ado_trajectories, t_horizon, modes=num_modes, ados=2)

    @staticmethod
    def test_build_connected_graph(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__,
                                   num_modes: int):
        ego_position = torch.rand(2)
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_position)
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()
        env.add_ado(position=torch.tensor([3, 0]), goal=torch.tensor([-4, 0]), num_modes=num_modes)
        env.add_ado(position=torch.tensor([5, 0]), goal=torch.tensor([-2, 0]), num_modes=num_modes)
        env.add_ado(position=torch.tensor([10, 0]), goal=torch.tensor([5, 3]), num_modes=num_modes)

        prediction_horizon = 10
        trajectory = torch.zeros((prediction_horizon, 4))  # does not matter here anyway
        graphs = env.build_connected_graph(ego_trajectory=trajectory)

        assert env.check_graph(graph=graphs, include_ego=True, t_horizon=prediction_horizon)

    @staticmethod
    def test_ego_graph_updates(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__,
                               num_modes: int):
        position = torch.tensor([-5, 0])
        goal = torch.tensor([5, 0])
        path = mantrap.utility.maths.straight_line(start=position, end=goal, steps=11)

        env = environment_class(mantrap.agents.IntegratorDTAgent, ego_position=position, ego_velocity=torch.zeros(2))
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()
        env.add_ado(position=torch.tensor([3, 0]), velocity=torch.ones(2), goal=torch.zeros(2), num_modes=num_modes)

        graphs = env.build_connected_graph(ego_trajectory=torch.cat((path, torch.zeros((11, 2))), dim=1))
        for k in range(path.shape[0]):
            path_point = graphs[f"{mantrap.constants.ID_EGO}_{k}_{mantrap.constants.GK_POSITION}"]
            assert torch.all(torch.eq(path[k, :], path_point))

    @staticmethod
    def test_detaching(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__, num_modes: int):
        ego_position = torch.rand(2)
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_position)
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()
        env.add_ado(position=torch.tensor([3, 0]), goal=torch.tensor([-4, 0]), num_modes=num_modes)
        env.add_ado(position=torch.tensor([-3, 2]), goal=torch.tensor([1, 5]), num_modes=num_modes)

        # Build computation graph to detach later on. Then check whether the graph has been been built by checking
        # for gradient availability.
        ego_control = torch.ones((1, 2))
        ego_control.requires_grad = True
        _, ado_controls, weights = env.predict_w_controls(ego_controls=ego_control, return_more=True)
        for j in range(env.num_ghosts):
            ado_id, _ = env.split_ghost_id(ghost_id=env.ghosts[j].id)
            i_ado = env.index_ado_id(ado_id=ado_id)
            env.ghosts[j].agent.update(action=ado_controls[i_ado, 0, 0, :], dt=env.dt)
        if env.is_differentiable_wrt_ego:
            assert env.ghosts[0].agent.position.grad_fn is not None

        # Detach computation graph.
        env.detach()
        assert env.ghosts[0].agent.position.grad_fn is None

    @staticmethod
    def test_copy(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__, num_modes: int):
        ego_init_pos = torch.tensor([-5, 0])
        ados_init_pos = torch.stack([torch.tensor([1.0, 0.0]), torch.tensor([-6, 2.5])])
        ados_init_vel = torch.stack([torch.tensor([4.2, -1]), torch.tensor([-7, -2.0])])
        ados_goal = torch.stack([torch.zeros(2), torch.ones(2)])

        # Create example environment scene to  copy later on. Then copy the example environment.
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_init_pos)
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()
        env.add_ado(position=ados_init_pos[0], velocity=ados_init_vel[0], goal=ados_goal[0], num_modes=num_modes)
        env.add_ado(position=ados_init_pos[1], velocity=ados_init_vel[1], goal=ados_goal[1], num_modes=num_modes)
        env_copy = env.copy()

        # Test equality of basic environment properties and states.
        assert env.name == env_copy.name
        assert env.time == env_copy.time
        assert env.dt == env_copy.dt

        assert env.same_initial_conditions(other=env_copy)
        assert env.num_ghosts == env_copy.num_ghosts
        assert env.num_modes == env_copy.num_modes
        assert env.ego == env_copy.ego
        for i in range(env.num_ghosts):  # agents should be equal and in the same order
            assert env.ghosts[i].agent == env_copy.ghosts[i].agent
            assert np.isclose(env.ghosts[i].weight, env_copy.ghosts[i].weight)
            assert env.ghosts[i].id == env_copy.ghosts[i].id
            for key in env.ghosts[i].params.keys():
                assert np.allclose(env.ghosts[i].params[key], env_copy.ghosts[i].params[key])
        ego_state_original, ado_states_original = env.states()
        ego_state_copy,  ado_states_copy = env_copy.states()
        assert torch.all(torch.eq(ego_state_original, ego_state_copy))
        assert torch.all(torch.eq(ado_states_original, ado_states_copy))

        # Test whether predictions are equal in both environments.
        ego_controls = torch.rand((5, 2))
        traj_original = env.predict_w_controls(ego_controls=ego_controls)
        traj_copy = env_copy.predict_w_controls(ego_controls=ego_controls)
        if env.is_deterministic:
            assert torch.all(torch.eq(traj_original, traj_copy))

        # Test broken link between `env` and `env_copy`, i.e. when I change env_copy, then the original
        # environment remains unchanged.
        env_copy.step(ego_action=torch.ones(2))  # does not matter here anyways
        ego_state_original, ado_states_original = env.states()
        ego_state_copy,  ado_states_copy = env_copy.states()
        assert not torch.all(torch.eq(ego_state_original, ego_state_copy))
        assert not torch.all(torch.eq(ado_states_original, ado_states_copy))

    @staticmethod
    def test_states(environment_class: mantrap.environment.base.GraphBasedEnvironment.__class__, num_modes: int):
        ego_position = torch.tensor([-5, 0])
        env = environment_class(ego_type=mantrap.agents.IntegratorDTAgent, ego_position=ego_position)
        if num_modes > 1 and not env.is_multi_modal:
            pytest.skip()
        env.add_ado(position=torch.tensor([3, 0]), velocity=torch.rand(2), goal=torch.rand(2), num_modes=num_modes)
        env.add_ado(position=torch.tensor([-4, 2]), velocity=torch.ones(2), goal=torch.rand(2), num_modes=num_modes)

        ego_state, ado_states = env.states()
        assert mantrap.utility.shaping.check_ego_state(x=ego_state, enforce_temporal=True)
        assert mantrap.utility.shaping.check_ado_states(x=ado_states, enforce_temporal=True)

        # The first entry of every predicted trajectory should be the current state, check that.
        ado_trajectories = env.predict_wo_ego(t_horizon=2)
        for m_mode in range(env.num_modes):
            assert torch.all(torch.eq(ado_states, ado_trajectories[:, m_mode, 0, :]))

        # Test that the states are the same as the states of actual agents.
        assert torch.all(torch.eq(ego_state, env.ego.state_with_time))
        for ghost in env.ghosts:
            m_ado, _ = env.convert_ghost_id(ghost_id=ghost.id)
            assert torch.all(torch.eq(ado_states[m_ado, :], ghost.agent.state_with_time))


###########################################################################
# Test - Iterative Environments ###########################################
###########################################################################
@pytest.mark.parametrize("env_class", [mantrap.environment.PotentialFieldEnvironment,
                                       mantrap.environment.SocialForcesEnvironment])
class TestParametrized:

    @staticmethod
    def test_parametrized_ghosts_init(env_class: mantrap.environment.base.IterativeEnvironment.__class__):
        position = torch.tensor([-1, 0])
        num_modes = 2
        # For the sake of easy testing simulate some kind of direc delta distribution.
        v0s = np.random.rand(num_modes)
        weights = np.random.rand(num_modes)
        s0s = np.random.rand(2)

        env = env_class()
        env.add_ado(goal=torch.zeros(2), position=position, num_modes=num_modes, weights=weights, v0s=v0s, sigmas=s0s)

        assert env.num_modes == num_modes
        assert all([env.split_ghost_id(ghost.id)[0] == env.ado_ids[0] for ghost in env.ghosts])
        assert len(env.ghosts) == num_modes

        v0s_env = np.array([ghost.params["v0"] for ghost in env.ghosts])
        assert np.allclose(v0s, v0s_env)


###########################################################################
# Test - Social Forces Environment ########################################
###########################################################################
@pytest.mark.parametrize("goal_position", [torch.tensor([2.0, 2.0]), torch.tensor([0.0, -2.0])])
def test_social_forces_single_ado_prediction(goal_position: torch.Tensor):
    env = mantrap.environment.SocialForcesEnvironment()
    env.add_ado(goal=goal_position, position=torch.tensor([-1, -5]), velocity=torch.ones(2) * 0.8, num_modes=1)

    trajectory = torch.squeeze(env.predict_wo_ego(t_horizon=100))
    assert torch.isclose(trajectory[-1][0], goal_position[0], atol=0.5)
    assert torch.isclose(trajectory[-1][1], goal_position[1], atol=0.5)


def test_social_forces_static_ado_pair_prediction():
    env = mantrap.environment.SocialForcesEnvironment()
    env.add_ado(goal=torch.zeros(2), position=torch.tensor([-1, 0]), velocity=torch.tensor([0.1, 0]), num_modes=1)
    env.add_ado(goal=torch.zeros(2), position=torch.tensor([1, 0]), velocity=torch.tensor([-0.1, 0]), num_modes=1)

    trajectories = env.predict_wo_ego(t_horizon=100)
    # Due to the repulsive of the agents between each other, they cannot both go to their goal position (which is
    # the same for both of them). Therefore the distance must be larger then zero basically, otherwise the repulsive
    # force would not act (or act attractive instead of repulsive).
    assert torch.norm(trajectories[0, -1, 0:1] - trajectories[1, -1, 0:1]) > 1e-3


###########################################################################
# Test - Potential Field Environment ######################################
###########################################################################
@pytest.mark.parametrize(
    "pos_1, pos_2",
    [
        (torch.tensor([1, 1]), torch.tensor([2, 2])),
        (torch.tensor([2, 0]), torch.tensor([4, 0])),
        (torch.tensor([0, 2]), torch.tensor([0, 4])),
    ],
)
def test_potential_field_forces(pos_1: torch.Tensor, pos_2: torch.Tensor):
    env_1 = mantrap.environment.PotentialFieldEnvironment(mantrap.agents.IntegratorDTAgent, ego_position=pos_1)
    env_2 = mantrap.environment.PotentialFieldEnvironment(mantrap.agents.IntegratorDTAgent, ego_position=pos_2)

    forces = torch.zeros((2, 2))
    gradients = torch.zeros((2, 2))
    for i, env in enumerate([env_1, env_2]):
        env.add_ado(position=torch.zeros(2), v0s=np.ones(1), weights=np.ones(1))
        graph = env.build_graph(ego_state=env.ego.state)
        forces[i, :] = graph[f"{env.ghosts[0].id}_0_{mantrap.constants.GK_CONTROL}"]
        ado_force_norm_0 = torch.norm(forces[i, :])
        ego_position_0 = graph[f"{mantrap.constants.ID_EGO}_0_{mantrap.constants.GK_POSITION}"]
        gradients[i, :] = torch.autograd.grad(ado_force_norm_0, ego_position_0, retain_graph=True)[0].detach()

    # The force is distance based, so more distant agents should affect a smaller force.
    assert torch.norm(forces[0, :]) > torch.norm(forces[1, :])
    assert torch.norm(gradients[0, :]) > torch.norm(gradients[1, :])
    # When the delta position is uni-directional, so e.g. just in x-position, the force as well as the gradient
    # should point only in this direction.
    for i, pos in enumerate([pos_1, pos_2]):
        for k in [0, 1]:
            if pos[k] == 0:
                assert forces[i, k] == gradients[i, k] == 0.0


###########################################################################
# Test - Trajectron Environment ###########################################
###########################################################################
def test_trajectron_mode_selection():
    num_modes = 2

    # Create distribution object similar to the Trajectron output.
    GMM2D = namedtuple("GMM2D", "mus log_pis")
    mus = torch.rand((1, 1, 1, num_modes * 2, 2))
    log_pis = torch.rand((1, 1, 1, num_modes * 2))
    gmm = GMM2D(mus=mus, log_pis=log_pis)

    # Determine trajectory from distribution. The time horizon `t_horizon` is the prediction horizon of the
    # simulation, however when predicting based on the applied controls of the ego then `t_horizon` is one step longer
    # than the number of control inputs, since the current state is prepended to the trajectories. Similarly, the
    # network prediction is one step longer, therefore we have to pass `t_horizon = 1 + 1 = 2` here.
    _, _, weight_indices = mantrap.environment.Trajectron.trajectory_from_distribution(
        gmm=gmm, num_output_modes=num_modes, dt=1.0, t_horizon=2, return_more=True, ado_state=torch.zeros(5)
    )

    # Test the obtained weight indices by checking for the smallest element in the GMM's "weights", which should be
    # related to the first (highest weight) index.
    log_pis = gmm.log_pis.permute(0, 1, 3, 2)[0, 0, :, :]
    pis = torch.exp(log_pis)
    assert np.argmax(pis) == weight_indices[0]


###########################################################################
# Test - SGAN Environment #################################################
###########################################################################
# def absolute_to_relative(trajectory: torch.Tensor) -> torch.Tensor:
#     t_horizon, num_agents, dim = trajectory.shape
#     trajectory_rel = trajectory - trajectory[0, :, :].unsqueeze(dim=0)
#     trajectory_rel = trajectory_rel[1:, :, :] - trajectory_rel[:-1, :, :]
#     return torch.cat((torch.zeros(1, num_agents, dim), trajectory_rel), dim=0)


###########################################################################
# Test - ORCA Environment #################################################
###########################################################################
# Comparison to original implementation of ORCA which can be found in
# external code directory and uses the following parameters:
# orca_rad = 1.0
# orca_dt = 10.0
# sim_dt = 0.25
# sim_speed_max = 4.0
@pytest.mark.xfail(raises=AssertionError)
def test_orca_single_agent():
    env = mantrap.environment.ORCAEnvironment(dt=0.25)
    env.add_ado(position=torch.zeros(2), velocity=torch.zeros(2), goal=torch.ones(2) * 4)

    pos_expected = torch.tensor([[0, 0], [0.70710, 0.70710], [1.4142, 1.4142], [2.1213, 2.1213], [2.8284, 2.8284]])
    ado_trajectories = env.predict_wo_ego(t_horizon=pos_expected.shape[0])
    assert torch.isclose(torch.norm(ado_trajectories[0, 0, :, 0:2] - pos_expected), torch.zeros(1), atol=0.1)


@pytest.mark.xfail(raises=AssertionError)
def test_orca_two_agents():
    env = mantrap.environment.ORCAEnvironment(dt=0.25)
    env.add_ado(position=torch.tensor([-5, 0.1]), velocity=torch.zeros(2), goal=torch.tensor([5, 0]))
    env.add_ado(position=torch.tensor([5, -0.1]), velocity=torch.zeros(2), goal=torch.tensor([-5, 0]))

    pos_expected = torch.tensor(
        [
            [
                [-5, 0.1],
                [-4.8998, 0.107995],
                [-4.63883, 0.451667],
                [-3.65957, 0.568928],
                [-2.68357, 0.6858],
                [-1.7121, 0.802128],
                [-0.747214, 0.917669],
                [0.207704, 1.03202],
                [1.18529, 0.821493],
                [2.16288, 0.61097],
            ],
            [
                [5, -0.1],
                [4.8998, -0.107995],
                [4.63883, -0.451667],
                [3.65957, -0.568928],
                [2.68357, -0.6858],
                [1.7121, -0.802128],
                [0.747214, -0.917669],
                [-0.207704, -1.03202],
                [-1.18529, -0.821493],
                [-2.16288, -0.61097],
            ],
        ]
    ).view(2, 1, -1, 2)
    ado_trajectories = env.predict_wo_ego(t_horizon=pos_expected.shape[2])
    assert torch.isclose(torch.norm(ado_trajectories[:, :, :, 0:2] - pos_expected), torch.zeros(1), atol=0.1)
