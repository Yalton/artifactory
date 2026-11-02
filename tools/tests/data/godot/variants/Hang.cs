using Godot;

namespace TrialGame;

// Autoload that never returns from _Ready, so the game never quits.
public partial class Hang : Node
{
    public override void _Ready()
    {
        ulong n = 0;
        while (true) { n++; }
    }
}
