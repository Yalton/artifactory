using Godot;

namespace LanternStub;

// Shows the node in group "dialogue" when `interact` is pressed within reach of the keeper.
public partial class Keeper : Node3D
{
    private const float Reach = 2.0f;

    public override void _UnhandledInput(InputEvent @event)
    {
        if (!@event.IsActionPressed("interact")) return;
        if (GetTree().GetFirstNodeInGroup("player") is not Node3D player) return;
        if (player.GlobalPosition.DistanceTo(GlobalPosition) > Reach) return;
        if (GetTree().GetFirstNodeInGroup("dialogue") is CanvasItem dialogue) dialogue.Visible = true;
    }
}
