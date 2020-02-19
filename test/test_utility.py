import time

import pytest
import torch

from mantrap.agents import IntegratorDTAgent
from mantrap.constants import agent_speed_max
from mantrap.utility.maths import Derivative2, lagrange_interpolation
from mantrap.utility.primitives import square_primitives, straight_line
from mantrap.utility.utility import build_trajectory_from_path


###########################################################################
# Utility Testing #########################################################
###########################################################################
def test_build_trajectory_from_positions():
    positions = straight_line(start_pos=torch.zeros(2), end_pos=torch.ones(2) * 10, steps=11)
    trajectory = build_trajectory_from_path(positions, dt=1.0, t_start=0.0)

    assert torch.all(torch.eq(trajectory[:, 0:2], positions))
    assert torch.all(torch.eq(trajectory[1:, 2:4], torch.ones(10, 2)))


###########################################################################
# Derivative2 Testing #####################################################
###########################################################################
@pytest.mark.parametrize("horizon", [7, 10])
def test_derivative_2(horizon: int):
    diff = Derivative2(horizon=horizon, dt=1.0)

    for k in range(1, horizon - 1):
        assert torch.all(torch.eq(diff._diff_mat[k, k - 1: k + 2], torch.tensor([1, -2, 1])))

    # Constant velocity -> zero acceleration (first and last point are skipped (!)).
    x = straight_line(torch.zeros(2), torch.tensor([horizon - 1, 0]), horizon)
    assert torch.all(torch.eq(diff.compute(x), torch.zeros((horizon, 2))))

    t_step = int(horizon / 2)
    x = torch.zeros((horizon, 2))
    x[t_step, 0] = 10
    x[t_step - 1, 0] = x[t_step + 1, 0] = 5
    x[t_step - 2, 0] = x[t_step + 2, 0] = 2
    a = diff.compute(x)

    assert torch.all(a[: t_step - 3, 0] == 0) and torch.all(a[t_step + 4:, 0] == 0)  # impact of acceleration
    assert torch.all(a[:, 1] == 0)  # no acceleration in y-direction
    assert a[t_step, 0] < 0 and a[t_step + 1, 0] > 0 and a[t_step - 1, 0] > 0  # peaks


def test_derivative_2_conserve_shape():
    x = torch.zeros((1, 1, 10, 6))
    diff = Derivative2(horizon=10, dt=1.0, num_axes=4)
    x_ddt = diff.compute(x)

    assert x.shape == x_ddt.shape


###########################################################################
# Interpolation Testing ###################################################
###########################################################################
def test_lagrange_interpolation():
    """Lagrange interpolation using Vandermonde Approach. Vandermonde finds the Lagrange parameters by solving
    a matrix equation X a = Y with known control point matrices (X,Y) and parameter vector a, therefore is fully
    differentiable. Also Lagrange interpolation guarantees to pass every control point, but performs poorly in
    extrapolation (which is however not required for trajectory fitting, since the trajectory starts and ends at
    defined control points.

    Source: http://www.maths.lth.se/na/courses/FMN050/media/material/lec8_9.pdf"""

    start = torch.tensor([0.0, 0.0])
    mid = torch.tensor([5.0, 5.0], requires_grad=True)
    end = torch.tensor([10.0, 0.0])
    points = torch.stack((start, mid, end))

    points_up = lagrange_interpolation(control_points=points, num_samples=100, deg=3)

    # Test trajectory shape and it itself.
    assert len(points_up.shape) == 2 and points_up.shape[1] == 2 and points_up.shape[0] == 100
    for n in range(100):
        assert start[0] <= points_up[n, 0] <= end[0]
        assert min(start[1], mid[1], end[1]) <= points_up[n, 1] + 0.0001
        assert points_up[n, 1] - 0.0001 <= max(start[1], mid[1], end[1])

    # Test derivatives of up-sampled trajectory.
    for n in range(1, 100):  # first point has no gradient since (0, 0) control point
        dx = torch.autograd.grad(points_up[n, 0], mid, retain_graph=True)[0]
        assert torch.all(torch.eq(dx, torch.zeros(2)))  # created by lin-space operation
        dy = torch.autograd.grad(points_up[n, 1], mid, retain_graph=True)[0]
        assert not torch.all(torch.eq(dy, torch.zeros(2)))  # created by interpolation


@pytest.mark.xfail(raises=RuntimeError)
def test_lagrange_singularity():
    start = torch.tensor([0.0, 0.0])
    mid = torch.tensor([0.0, 5.0], requires_grad=True)
    end = torch.tensor([10.0, 0.0])
    points = torch.stack((start, mid, end))

    points_up = lagrange_interpolation(control_points=points, num_samples=10)
    for n in range(1, 10):
        torch.autograd.grad(points_up[n, 0], mid, retain_graph=True)
        torch.autograd.grad(points_up[n, 1], mid, retain_graph=True)


###########################################################################
# Primitives ##############################################################
###########################################################################
@pytest.mark.parametrize("num_points", [5, 10])
def test_square_primitives(num_points: int):
    position, velocity, goal = torch.tensor([-5, 0]), torch.tensor([1, 0]), torch.tensor([20, 0])
    agent = IntegratorDTAgent(position=position, velocity=velocity)
    primitives = square_primitives(start=agent.position, end=goal, dt=1.0, steps=num_points)

    assert primitives.shape[1] == num_points
    for m in range(primitives.shape[0]):
        for i in range(1, num_points - 1):
            distance = torch.norm(primitives[m, i, :] - primitives[m, i - 1, :])
            distance_next = torch.norm(primitives[m, i + 1, :] - primitives[m, i, :])
            if torch.isclose(distance_next, torch.zeros(1), atol=0.1):
                continue
            tolerance = agent_speed_max / 10
            assert torch.isclose(distance, torch.tensor([agent_speed_max]).double(), atol=tolerance)  # dt = 1.0

    # The center primitive should be a straight line, therefore the one with largest x-expansion, since we are moving
    # straight in x-direction. Similarly the first primitive should have the largest expansion in y direction, the
    # last one the smallest.
    assert all([primitives[1, -1, 0] >= primitives[i, -1, 0] for i in range(primitives.shape[0])])
    assert all([primitives[0, -1, 1] >= primitives[i, -1, 1] for i in range(primitives.shape[0])])
    assert all([primitives[-1, -1, 1] <= primitives[i, -1, 1] for i in range(primitives.shape[0])])