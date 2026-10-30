using Godot;

namespace TrialGame;

public partial class Player : Node3D
{
    private const float Speed = 4.0f;

    public override void _PhysicsProcess(double delta)
    {
        Vector2 input = Input.GetVector("move_left", "move_right", "move_forward", "move_back");
        Position += new Vector3(input.X, 0, input.Y) * Speed * (float)delta;
    }
}
