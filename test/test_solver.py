import time
from typing import Tuple, Union

import numpy as np
import pytest
import torch

from mantrap.constants import agent_speed_max, constraint_min_distance
from mantrap.agents import IntegratorDTAgent
from mantrap.simulation import PotentialFieldSimulation
from mantrap.simulation.simulation import GraphBasedSimulation
from mantrap.solver import MonteCarloTreeSearch, SGradSolver, IGradSolver, ORCASolver
from mantrap.solver.solver import Solver
from mantrap.solver.ipopt_solver import IPOPTSolver
from mantrap.utility.shaping import check_ego_trajectory


def scenario(solver_class: Solver.__class__, **solver_kwargs):
    ego_pos = torch.tensor([-5, 2])
    ego_goal = torch.tensor([1, 1])
    ado_poses = [torch.tensor([3, 2])]

    sim = PotentialFieldSimulation(IntegratorDTAgent, {"position": ego_pos})
    for pos in ado_poses:
        sim.add_ado(position=pos)
    solver = solver_class(sim, goal=ego_goal, **solver_kwargs)
    z0 = solver.z0s_default(just_one=True).detach().numpy()
    return sim, solver, z0


###########################################################################
# Test - Base Solver ######################################################
###########################################################################
# In order to test the general functionality of the solver base class, the solver is redefined to always follow
# a specific action, e.g. always going in positive x direction with constant and pre-determined speed. Then,
# the results are directly predictable and hence testable.
class ConstantSolver(Solver):
    def determine_ego_controls(self, **solver_kwargs) -> torch.Tensor:
        controls = torch.zeros((self.T - 1, 2))
        controls[0, 0] = 1.0
        return controls

    def initialize(self, **solver_params):
        pass

    def num_optimization_variables(self) -> int:
        return self.T


def test_solve():
    sim = PotentialFieldSimulation(IntegratorDTAgent, {"position": torch.tensor([-8, 0])})
    sim.add_ado(position=torch.tensor([0, 0]), velocity=torch.tensor([-1, 0]))
    solver = ConstantSolver(sim, goal=torch.zeros(2), t_planning=10, objectives=[], constraints=[])

    assert solver.T == 10
    assert torch.all(torch.eq(solver.goal, torch.zeros(2)))

    x5_opt, ado_trajectories, x5_opt_planned = solver.solve(100)

    # Test output shapes.
    t_horizon_exp = int(8 / sim.dt)  # distance ego position and goal = 8 / velocity 1.0 = 8.0 s
    assert check_ego_trajectory(x5_opt, t_horizon=t_horizon_exp)
    assert tuple(ado_trajectories.shape) == (t_horizon_exp, 1, 1, solver.T, 5)
    assert tuple(x5_opt_planned.shape) == (t_horizon_exp, solver.T, 5)

    # Test ego output trajectory.
    x_path_exp = torch.tensor([-8.0 + 1.0 * sim.dt * k for k in range(t_horizon_exp)])
    assert torch.all(torch.isclose(x5_opt[:, 0], x_path_exp, atol=1e-3))
    assert torch.all(torch.eq(x5_opt[:, 1], torch.zeros(t_horizon_exp)))

    assert torch.isclose(x5_opt[0,  2], torch.zeros(1))
    assert torch.all(torch.isclose(x5_opt[1:, 2], torch.ones(t_horizon_exp - 1)))
    assert torch.all(torch.eq(x5_opt[:, 3], torch.zeros(t_horizon_exp)))

    time_steps_exp = torch.tensor([k * sim.dt for k in range(t_horizon_exp)])
    assert torch.all(torch.isclose(x5_opt[:, -1], time_steps_exp))

    # Test ego planned trajectories - independent on simulation engine. The ConstantSolver`s returned action
    # is always going straight with constant speed and direction, but just lasting for the first control step. Since
    # the ego is a single integrator agent, for the full remaining trajectory it stays at the point it went to
    # at the beginning (after the fist control loop).
    for k in range(t_horizon_exp - 1):
        assert torch.all(torch.isclose(x5_opt_planned[k, 1:, 0], torch.ones(solver.T - 1) * (x5_opt[k + 1, 0])))
        assert torch.all(torch.eq(x5_opt_planned[k, :, 1], torch.zeros(solver.T)))
        time_steps_exp = torch.tensor([x5_opt[k, -1] + i * sim.dt for i in range(solver.T)])
        assert torch.all(torch.isclose(x5_opt_planned[k, :, -1], time_steps_exp))

    # Test ado planned trajectories - depending on simulation engine. Therefore only time-stamps can be tested.
    for k in range(t_horizon_exp):
        time_steps_exp = torch.tensor([x5_opt[k, -1] + i * sim.dt for i in range(solver.T)])
        assert torch.all(torch.isclose(x5_opt_planned[k, :, -1], time_steps_exp))


###########################################################################
# Tests - All Solvers #####################################################
###########################################################################
# In order to test the general functionality of the solver base class, a simple optimization problem is
# created and solved, so that the feasibility of the result can be checked easily. This simple optimization problem
# basically is potential field (distance field) around a fixed point. In order to create this scenario an unconstrained
# optimization problem is posed with only a goal-based objective and no interaction with other agents. Then, all
# trajectory points should converge to the same point (which is the goal point).
@pytest.mark.parametrize(
    "solver_class", (MonteCarloTreeSearch, IGradSolver, SGradSolver)
)
class TestSolvers:

    @staticmethod
    def test_convergence(solver_class: Solver.__class__):
        sim = PotentialFieldSimulation(IntegratorDTAgent, {"position": torch.tensor([-agent_speed_max/2, 0])}, dt=1.0)
        solver = solver_class(sim, goal=torch.zeros(2), t_planning=3, objectives=[("goal", 1.0)], constraints=[])

        ego_controls = solver.determine_ego_controls(max_cpu_time=1.0, max_iter=1000, multiprocessing=True)
        x5_opt = solver.env.ego.unroll_trajectory(controls=ego_controls, dt=solver.env.dt)

        assert torch.all(torch.isclose(x5_opt[0, :], sim.ego.state_with_time))
        for k in range(1, solver.T):
            assert torch.all(torch.isclose(x5_opt[k, 0:2], solver.goal, atol=0.5))

    @staticmethod
    def test_formulation(solver_class: Solver.__class__):
        sim, solver, z0 = scenario(solver_class)

        # Test output shapes.
        objective = solver.objective(z=z0)
        assert type(objective) == float
        constraints = solver.constraints(z=z0, return_violation=False)
        assert constraints.size == sum([c.num_constraints for c in solver.constraint_modules.values()])

    @staticmethod
    def test_x_to_x2(solver_class: IPOPTSolver.__class__):
        sim, solver, z0 = scenario(solver_class)
        x0 = solver.z_to_ego_trajectory(z0).detach().numpy()[:, 0:2]

        x02 = np.reshape(x0, (-1, 2))
        for xi in x02:
            assert any([np.isclose(np.linalg.norm(xk - xi), 0, atol=2.0) for xk in x0])

    @staticmethod
    def test_runtime(solver_class: IPOPTSolver.__class__):
        sim, solver, z0 = scenario(solver_class)

        comp_times_objective = []
        comp_times_constraints = []
        for _ in range(10):
            start_time = time.time()
            solver.constraints(z=z0)
            comp_times_constraints.append(time.time() - start_time)
            start_time = time.time()
            solver.objective(z=z0)
            comp_times_objective.append(time.time() - start_time)

        assert np.mean(comp_times_objective) < 0.04  # faster than 25 Hz (!)
        assert np.mean(comp_times_constraints) < 0.04  # faster than 25 Hz (!)


###########################################################################
# Test - IPOPT Solver #####################################################
###########################################################################
@pytest.mark.parametrize(
    "solver_class", (IGradSolver, SGradSolver)
)
class TestIPOPTSolvers:

    @staticmethod
    def test_formulation(solver_class: IPOPTSolver.__class__):
        sim, solver, z0 = scenario(solver_class)

        # Test output shapes.
        grad = solver.gradient(z=z0)
        assert np.linalg.norm(grad) > 0
        assert grad.size == z0.flatten().size
        jacobian = solver.jacobian(z0)
        num_constraints = sum([c.num_constraints for c in solver.constraint_modules.values()])
        assert jacobian.size == num_constraints * z0.flatten().size

        # Test derivatives using derivative-checker from IPOPT framework, format = "mine ~ estimated (difference)".
        if solver.is_verbose:
            x0 = torch.from_numpy(z0)
            solver.solve_single_optimization(x0, approx_jacobian=False, approx_hessian=True, check_derivative=True)

    @staticmethod
    def test_runtime(solver_class: IPOPTSolver.__class__):
        sim, solver, z0 = scenario(solver_class)

        comp_times_jacobian = []
        comp_times_gradient = []
        for _ in range(10):
            start_time = time.time()
            solver.gradient(z=z0)
            comp_times_gradient.append(time.time() - start_time)
            start_time = time.time()
            solver.jacobian(z=z0)
            comp_times_jacobian.append(time.time() - start_time)
        assert np.mean(comp_times_jacobian) < 0.07  # faster than 15 Hz (!)
        assert np.mean(comp_times_gradient) < 0.07  # faster than 15 Hz (!)


def test_s_grad_solver():
    env = PotentialFieldSimulation(IntegratorDTAgent, {"position": torch.tensor([-5, 0.5])})
    env.add_ado(position=torch.tensor([0, 0]), velocity=torch.tensor([-1, 0]))
    c_grad_solver = SGradSolver(env, goal=torch.tensor([5, 0]), t_planning=10, verbose=False)

    from mantrap.utility.primitives import square_primitives
    x0 = square_primitives(start=env.ego.position, end=c_grad_solver.goal, dt=env.dt, steps=11)[1]
    x40 = env.ego.expand_trajectory(x0, dt=env.dt)
    u0 = env.ego.roll_trajectory(x40, dt=env.dt)

    x_solution = c_grad_solver.solve_single_optimization(z0=u0, max_cpu_time=5.0)
    ado_trajectories = env.predict_w_trajectory(trajectory=x_solution)

    for t in range(10):
        for m in range(env.num_ado_ghosts):
            assert torch.norm(x_solution[t, 0:2] - ado_trajectories[m, :, t, 0:2]).item() >= constraint_min_distance


###########################################################################
# Test - ORCA Solver ######################################################
###########################################################################
class ORCASimulation(GraphBasedSimulation):

    orca_rad = 1.0
    orca_dt = 10.0
    sim_dt = 0.25
    sim_speed_max = 4.0

    def __init__(self, ego_type=None, ego_kwargs=None, **kwargs):
        super(ORCASimulation, self).__init__(ego_type, ego_kwargs, dt=self.sim_dt, **kwargs)
        self._ado_goals = []

    def add_ado(self, goal_position: Union[torch.Tensor, None], **ado_kwargs):
        super(ORCASimulation, self).add_ado(type=IntegratorDTAgent, log=False, **ado_kwargs)
        self._ado_goals.append(goal_position)

    def step(self, ego_policy: torch.Tensor = None) -> Tuple[torch.Tensor, Union[torch.Tensor, None]]:
        self._sim_time = self.sim_time + self.dt

        assert self._ego is None, "simulation merely should have ado agents"
        assert all([ado.__class__ == IntegratorDTAgent for ado in self._ados]), "agents should be single integrators"

        controls = torch.zeros((self.num_ados, 2))
        for ia, ado in enumerate(self._ados):
            ado_kwargs = {"position": ado.position, "velocity": ado.velocity, "log": False}
            ado_env = ORCASimulation(IntegratorDTAgent, ego_kwargs=ado_kwargs)
            for other_ado in self._ados[:ia] + self._ados[ia + 1 :]:  # all agent except current loop element
                ado_env.add_ado(position=other_ado.position, velocity=other_ado.velocity, goal_position=None)

            ado_solver = ORCASolver(ado_env, goal=self._ado_goals[ia], t_planning=1)
            controls[ia, :] = ado_solver.determine_ego_controls(
                speed_max=self.sim_speed_max, agent_radius=self.orca_rad, safe_dt=self.orca_dt
            )

        for i, ado in enumerate(self._ados):
            ado.update(controls[i, :], dt=self.dt)
        return torch.stack([ado.state for ado in self._ados]), None


def test_single_agent():
    pos_init = torch.zeros(2)
    vel_init = torch.zeros(2)
    goal_pos = torch.ones(2) * 4

    pos_expected = torch.tensor([[0, 0], [0.70710, 0.70710], [1.4142, 1.4142], [2.1213, 2.1213], [2.8284, 2.8284]])

    sim = ORCASimulation()
    sim.add_ado(position=pos_init, velocity=vel_init, goal_position=goal_pos)

    assert sim.num_ados == 1
    assert torch.all(torch.eq(sim.ados[0].position, pos_init))
    assert torch.all(torch.eq(sim.ados[0].velocity, vel_init))

    pos = torch.zeros(pos_expected.shape)

    pos[0, :] = sim.ados[0].position
    for k in range(1, pos.shape[0]):
        state_k, _ = sim.step()
        pos[k, :] = state_k[0, :2]

    assert torch.isclose(torch.norm(pos - pos_expected), torch.zeros(1), atol=0.1)


def test_two_agents():
    pos_init = torch.tensor([[-5, 0.1], [5, -0.1]])
    vel_init = torch.zeros((2, 2))
    goal_pos = torch.tensor([[5, 0], [-5, 0]])

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
    )

    sim = ORCASimulation()
    sim.add_ado(position=pos_init[0, :], velocity=vel_init[0, :], goal_position=goal_pos[0, :])
    sim.add_ado(position=pos_init[1, :], velocity=vel_init[1, :], goal_position=goal_pos[1, :])

    pos = torch.zeros(pos_expected.shape)
    pos[0, 0, :] = sim.ados[0].position
    pos[1, 0, :] = sim.ados[1].position
    for k in range(1, pos.shape[1]):
        state_k, _ = sim.step()
        pos[:, k, :] = state_k[:, :2]

    assert torch.isclose(torch.norm(pos - pos_expected), torch.zeros(1), atol=0.1)