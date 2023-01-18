# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.14.1
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# # Stokes equations with various stable pairs of finite elements
#
# ## Equation and problem definition
#
# ### Strong formulation
#
# $$
# -\nabla \cdot (\nabla u + p I) = f \; {\rm in} \; \Omega, \quad \nabla \cdot u = 0 \; {\rm in} \; \Omega
# $$
#
# A typical set of boundary conditions on the boundary $\partial\Omega = \Gamma_{D} \cup \Gamma_{N}$ can be:
#
# $$
# u = u_0 \; {\rm on} \; \Gamma_{D}, \quad \nabla u \cdot n + p n = g \; {\rm on} \; \Gamma_{N}.
# $$
#
# ### Weak formulation
#
# We formulate the Stokes equations' mixed variational form; that is, a
# form where the two variables, the velocity and the pressure, are
# approximated. We have the problem: find $(u, p) \in W$ such that
#
# $$
# a((u, p), (v, q)) = L((v, q))
# $$
#
# for all $(v, q) \in W$, where
#
# $$
# a((u, p), (v, q)) := \int_{\Omega} \nabla u \cdot \nabla v - \nabla \cdot v \; p + \nabla \cdot u \; q \, {\rm d} x,
# $$
#
# $$
# L((v, q)) := \int_{\Omega} f \cdot v \, {\rm d} x + \int_{\partial \Omega_N} g \cdot v \, {\rm d} s.
# $$
#
# The space $W$ is a mixed (product) function space $W = V \times Q$, such that $u \in V$ and $q \in Q$.
#
# ### Domain and boundary conditions
#
# We define the lid-driven cavity problem with the following
# domain and boundary conditions:
#
# - $\Omega = [0,1]\times[0,1]$ (a unit square)
# - $\Gamma_D = \partial \Omega$
# - $u_0 = (1, 0)^\top$ at $x_1 = 1$ and $u_0 = (0,
#   0)^\top$ otherwise
# - $f = (0, 0)^\top$
#
# ### Discretization
#
# There are many ways to choose the discretized function spaces $V_h \subset V$ and $Q_h \subset Q$ for the
# mixed variational form.
# Care must be taken that the combination of $V_h$ and $Q_h$ is stable in the sense of the inf-sup condition.
# Common are the following stable pairs:
#
# 1. $(\mathcal{P}_2, \mathcal{P}_1$): The Taylor Hood element for $k=2$
# 2. $(\mathcal{P}_1 + \mathcal{B}_3, \mathcal{P}_1)$: The MINI element
# 3. $(\mathcal{P}_1^{\rm CR}, \mathcal{P}_0)$: The non-conforming Crouzeix-Raviart element
#
# In the following, the Stokes equations in the lid-driven cavity setting are solved using each of these stable pairs.
#
# ## Implementation
#
# We first import the modules and functions that the program uses:

# +
import numpy as np

import ufl
from dolfinx import fem
from dolfinx.fem import (Constant, Function, FunctionSpace, dirichletbc,
                         form, locate_dofs_topological)
from dolfinx.io import XDMFFile
from dolfinx.mesh import (CellType, GhostMode, create_rectangle,
                          locate_entities_boundary)
from ufl import div, dx, grad, inner

from mpi4py import MPI
from petsc4py import PETSc

# -

# We create a {py:class}`Mesh <dolfinx.mesh.Mesh>`, define functions to
# geometrically locate subsets of its boundary and define a function
# describing the velocity to be imposed as a boundary condition in a lid
# driven cavity problem:

# +
# Create mesh
msh = create_rectangle(MPI.COMM_WORLD,
                       [np.array([0, 0]), np.array([1, 1])],
                       [32, 32],
                       CellType.triangle, GhostMode.none)


# Function to mark x = 0, x = 1 and y = 0
def noslip_boundary(x):
    return np.logical_or(np.logical_or(np.isclose(x[0], 0.0),
                                       np.isclose(x[0], 1.0)),
                         np.isclose(x[1], 0.0))


# Function to mark the lid (y = 1)
def lid(x):
    return np.isclose(x[1], 1.0)


# Lid velocity
def lid_velocity_expression(x):
    return np.stack((np.ones(x.shape[1]), np.zeros(x.shape[1])))


# -

# ### 1. $(\mathcal{P}_2, \mathcal{P}_1$): The Taylor Hood element for $k=2$
#
# For the Taylor Hood, the discrete function spaces are chosen as $V_h = \mathcal{P}_k$ and
# $Q_h = \mathcal{P}_{k-1}$ with $k \geq 2$.
#
# For $k = 2$ we have:

# +
P2 = ufl.VectorElement("Lagrange", msh.ufl_cell(), 2)
P1 = ufl.FiniteElement("Lagrange", msh.ufl_cell(), 1)
V, Q = FunctionSpace(msh, P2), FunctionSpace(msh, P1)

(u, p) = ufl.TrialFunction(V), ufl.TrialFunction(Q)
(v, q) = ufl.TestFunction(V), ufl.TestFunction(Q)


# -

# First, we have to define the boundary conditions for the velocity field in the problem setting.
# In the case of the lid driven cavity scenario, there is a driving velocity condition on the top boundary
# and a no-slip boundary condition on the remaining boundary.

# +
def define_bcs(V):
    # No-slip boundary condition for velocity field (`V`) on boundaries
    # where x = 0, x = 1, and y = 0
    noslip = np.zeros(msh.geometry.dim, dtype=PETSc.ScalarType)
    facets = locate_entities_boundary(msh, 1, noslip_boundary)
    bc0 = dirichletbc(noslip, locate_dofs_topological(V, 1, facets), V)

    # Driving velocity condition u = (1, 0) on top boundary (y = 1)
    lid_velocity = Function(V)
    lid_velocity.interpolate(lid_velocity_expression)
    facets = locate_entities_boundary(msh, 1, lid)
    bc1 = dirichletbc(lid_velocity, locate_dofs_topological(V, 1, facets))

    # Collect Dirichlet boundary conditions
    bcs = [bc0, bc1]
    return bcs


bcs = define_bcs(V)


# -

# The variational problem for the Stokes equations can be defined as follows:

# +
def define_weak_form(u, p, v, q):
    # Define variational problem
    f = Constant(msh, (PETSc.ScalarType(0), PETSc.ScalarType(0)))

    a = form([[inner(grad(u), grad(v)) * dx, inner(p, div(v)) * dx],
              [inner(div(u), q) * dx, None]])
    L = form([inner(f, v) * dx, inner(Constant(msh, PETSc.ScalarType(0)), q) * dx])
    return a, L


a, L = define_weak_form(u, p, v, q)


# -

# Before the solution can be obtained, the linear system has to be assembled. We set a null space to account
# for the homogeneous Neumann boundary conditions of the pressure field.

# +
def assemble_system(a, L, bcs, V):
    A = fem.petsc.assemble_matrix_block(a, bcs=bcs)
    A.assemble()
    b = fem.petsc.assemble_vector_block(L, a, bcs=bcs)

    # Set near nullspace for pressure
    null_vec = A.createVecLeft()
    offset = V.dofmap.index_map.size_local * V.dofmap.index_map_bs
    null_vec.array[offset:] = 1.0
    null_vec.normalize()
    nsp = PETSc.NullSpace().create(vectors=[null_vec])
    assert nsp.test(A)
    A.setNullSpace(nsp)
    return A, b


A, b = assemble_system(a, L, bcs, V)


# -

# Finally, the linear system can be solved to obtain the solution functions $u$ and $p$. Here, a direct solver is used.

# +
def solve_system(A, b, msh, V):
    # Create LU solver
    ksp = PETSc.KSP().create(msh.comm)
    ksp.setOperators(A)
    ksp.setType("preonly")
    ksp.getPC().setType("lu")
    ksp.getPC().setFactorSolverType("superlu_dist")

    # Compute solution
    x = A.createVecLeft()
    ksp.solve(b, x)

    # Create Functions and scatter x solution
    u, p = Function(V), Function(Q)
    V_map = V.dofmap.index_map
    offset = V_map.size_local * V.dofmap.index_map_bs
    u.x.array[:offset] = x.array_r[:offset]
    p.x.array[:(len(x.array_r) - offset)] = x.array_r[offset:]
    return u, p


u, p = solve_system(A, b, msh, V)


# -

# Print the norm of the solved velocity and pressure coefficient vectors:

# +
def l2_norm(sol):
    comm = sol.function_space.mesh.comm
    error = form(sol**2 * ufl.dx)
    return np.sqrt(comm.allreduce(fem.assemble_scalar(error), MPI.SUM))


coef_norm_u_1 = u.x.norm()
coef_norm_p_1 = p.x.norm()
l2_norm_u_1 = l2_norm(u)
l2_norm_p_1 = l2_norm(p)
if MPI.COMM_WORLD.rank == 0:
    print("(1) Norm of velocity coefficient vector with the Taylor Hood element:      {}".format(coef_norm_u_1))
    print("(1) Norm of pressure coefficient vector with the Taylor Hood element:      {}".format(coef_norm_p_1))
    print("(1) L2 Norm of the velocity field with the Taylor Hood element:            {}".format(l2_norm_u_1))
    print("(1) L2 Norm of pressure field with the Taylor Hood element:                {}".format(l2_norm_p_1))


# -

# The solved velocity and pressure fields are saved as XDMF files and can be visualized e.g. in Paraview.

# +
def save_solution(sol, file_name):
    with XDMFFile(MPI.COMM_WORLD, file_name, "w") as file_xdmf:
        sol.x.scatter_forward()
        file_xdmf.write_mesh(msh)
        file_xdmf.write_function(sol)


save_solution(u, "out_stokes_stable_pairs/1_velocity.xdmf")
save_solution(p, "out_stokes_stable_pairs/1_pressure.xdmf")
# -

# ### 2. $(\mathcal{P}_1 + \mathcal{B}_3, \mathcal{P}_1)$: The MINI element

# For the so-called [MINI element](https://defelement.com/elements/mini.html) the finite element for
# the velocity field is chosen as the Lagrange element of degree 1 enriched with a
# [bubble element](https://defelement.com/elements/bubble.html) of degree 3.
# The finite element for the pressure field is chosen as Lagrange element of degree 1.
#
# In `dolfinx`, enriched finite elements can be obtained simply by using the `+` operator.

# +
P1 = ufl.FiniteElement("Lagrange", msh.ufl_cell(), 1)
B = ufl.FiniteElement("Bubble", msh.ufl_cell(), 3)
V_enriched = ufl.VectorElement(P1 + B)
V, Q = FunctionSpace(msh, V_enriched), FunctionSpace(msh, P1)

(u, p) = ufl.TrialFunction(V), ufl.TrialFunction(Q)
(v, q) = ufl.TestFunction(V), ufl.TestFunction(Q)
# -

# We solve the Stokes equations as before but this time using the MINI element.
# Subsequently, the solved velocity and pressure fields are saved.

bcs = define_bcs(V)
a, L = define_weak_form(u, p, v, q)
A, b = assemble_system(a, L, bcs, V)
u, p = solve_system(A, b, msh, V)
coef_norm_u_2 = u.x.norm()
coef_norm_p_2 = p.x.norm()
l2_norm_u_2 = l2_norm(u)
l2_norm_p_2 = l2_norm(p)
if MPI.COMM_WORLD.rank == 0:
    print("(2) Norm of velocity coefficient vector with the MINI element:             {}".format(coef_norm_u_2))
    print("(2) Norm of pressure coefficient vector with the MINI element:             {}".format(coef_norm_p_2))
    print("(2) L2 Norm of the velocity field with the MINI element:                   {}".format(l2_norm_u_2))
    print("(2) L2 Norm of pressure field with the MINI element:                       {}".format(l2_norm_p_2))
save_solution(u, "out_stokes_stable_pairs/2_velocity.xdmf")
save_solution(p, "out_stokes_stable_pairs/2_pressure.xdmf")

# ### 3. $(\mathcal{P}_1^{\rm CR}, \mathcal{P}_0)$: The non-conforming Crouzeix-Raviart element
#
# Another possibility for chosing the discretized function spaces is by using the
# [Crouzeix-Raviart element](https://defelement.com/elements/crouzeix-raviart.html).
# Here, a non-conforming variant of the Lagrange element of degree 1 is used for the velocity field,
# whereas the DG element is used for the pressure field.

# +
P1CR = ufl.VectorElement("Crouzeix-Raviart", msh.ufl_cell(), 1)
P0 = ufl.FiniteElement("DG", msh.ufl_cell(), 0)
V, Q = FunctionSpace(msh, P1CR), FunctionSpace(msh, P1)

(u, p) = ufl.TrialFunction(V), ufl.TrialFunction(Q)
(v, q) = ufl.TestFunction(V), ufl.TestFunction(Q)
# -

# We solve the Stokes equations as before but this time using the Crouzeix-Raviart element.
# Subsequently, the solved velocity and pressure fields are saved.

bcs = define_bcs(V)
a, L = define_weak_form(u, p, v, q)
A, b = assemble_system(a, L, bcs, V)
u, p = solve_system(A, b, msh, V)
coef_norm_u_3 = u.x.norm()
coef_norm_p_3 = p.x.norm()
l2_norm_u_3 = l2_norm(u)
l2_norm_p_3 = l2_norm(p)
if MPI.COMM_WORLD.rank == 0:
    print("(3) Norm of velocity coefficient vector with the Crouzeix-Raviart element: {}".format(coef_norm_u_3))
    print("(3) Norm of pressure coefficient vector with the Crouzeix-Raviart element: {}".format(coef_norm_p_3))
    print("(3) L2 Norm of the velocity field with the Crouzeix-Raviart element:       {}".format(l2_norm_u_3))
    print("(3) L2 Norm of pressure field with the Crouzeix-Raviart element:           {}".format(l2_norm_p_3))
save_solution(u, "out_stokes_stable_pairs/3_velocity.xdmf")
save_solution(p, "out_stokes_stable_pairs/3_pressure.xdmf")

# ## Interpretation
#
# We solved the Stokes equations for the lid driven cavity setting using different stable pairs of finite elements.
# Due to the rather coarse discretization, slight differences in the velocity field can be observed (e.g. in Paraview),
# but these gradually disappear with finer discretization. The pressure field is only determined except to a constant
# due to the homogeneous Neumann boundary conditions and therefore the L2 norms of the pressure field can differ
# from each other a lot. Due to the different basis functions, the solved coefficients are completely different
# despite the almost coinciding velocity field.
