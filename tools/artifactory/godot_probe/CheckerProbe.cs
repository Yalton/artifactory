// Injected by the Artifactory Godot checker into a copy of the trial project.
// Presses W, then D, and reports whether the node in group "player" moved.
using System.Globalization;
using Godot;

namespace ArtifactoryChecker;

public partial class CheckerProbe : Node
{
    private ulong _start;
    private int _stage;
    private Node3D _player;
    private Vector3 _p0, _p1, _p2;
    private string _problem;

    public override void _Ready()
    {
        ProcessMode = ProcessModeEnum.Always;
        _start = Time.GetTicksMsec();
    }

    public override void _Process(double delta)
    {
        double t = (Time.GetTicksMsec() - _start) / 1000.0;
        switch (_stage)
        {
            case 0 when t >= 1.0:
                FindPlayer();
                if (_player != null) _p0 = _player.GlobalPosition;
                SendKey(Key.W, true);
                _stage = 1;
                break;
            case 1 when t >= 2.0:
                SendKey(Key.W, false);
                if (Valid()) _p1 = _player.GlobalPosition;
                SendKey(Key.D, true);
                _stage = 2;
                break;
            case 2 when t >= 3.0:
                SendKey(Key.D, false);
                if (Valid()) _p2 = _player.GlobalPosition;
                Report();
                _stage = 3;
                break;
            case 3 when t >= 3.5:
                _stage = 4;
                GetTree().Quit();
                break;
        }
    }

    private void FindPlayer()
    {
        int count = 0;
        foreach (Node n in GetTree().GetNodesInGroup("player"))
        {
            if (n is Node3D n3)
            {
                count++;
                _player = n3;
            }
        }
        if (count != 1)
        {
            _player = null;
            _problem = $"found {count} Node3D in group player";
        }
    }

    private bool Valid()
    {
        if (_player != null && !IsInstanceValid(_player))
        {
            _player = null;
            _problem = "player node was freed";
        }
        return _player != null;
    }

    private static void SendKey(Key key, bool pressed)
    {
        var ev = new InputEventKey
        {
            Keycode = key,
            PhysicalKeycode = key,
            Pressed = pressed,
        };
        Input.ParseInputEvent(ev);
    }

    private void Report()
    {
        if (!Valid())
        {
            GD.Print($"PROBE player_moves=false w=0 d=0 problem={_problem}");
            return;
        }
        Vector3 w = _p1 - _p0;
        Vector3 d = _p2 - _p1;
        bool differ = w.Length() > 0.1f && d.Length() > 0.1f
            && (w.Normalized() - d.Normalized()).Length() > 0.1f;
        string ws = w.Length().ToString("0.###", CultureInfo.InvariantCulture);
        string ds = d.Length().ToString("0.###", CultureInfo.InvariantCulture);
        GD.Print($"PROBE player_moves={(differ ? "true" : "false")} w={ws} d={ds}");
    }
}
