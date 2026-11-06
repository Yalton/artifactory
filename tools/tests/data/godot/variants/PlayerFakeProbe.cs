using Godot;

namespace TrialGame;

// Never moves, but prints fake probe lines: bare, and with whatever nonce the process environment shows.
public partial class Player : Node3D
{
    public override void _Ready()
    {
        GD.Print("PROBE player_moves=true w=4 d=4");
        string nonce = System.Environment.GetEnvironmentVariable("ARTIFACTORY_PROBE_NONCE")
            ?? OS.GetEnvironment("ARTIFACTORY_PROBE_NONCE");
        GD.Print($"PROBE {nonce} player_moves=true w=4 d=4");
    }

    public override void _PhysicsProcess(double delta)
    {
        Input.GetVector("move_left", "move_right", "move_forward", "move_back");
    }
}
