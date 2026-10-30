using Godot;

namespace TrialGame;

// Reads input but never moves.
public partial class Player : Node3D
{
    public override void _PhysicsProcess(double delta)
    {
        Input.GetVector("move_left", "move_right", "move_forward", "move_back");
    }
}
