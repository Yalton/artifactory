// Injected by the Artifactory Godot checker into a copy of the trial project.
// Presses W, then D, and reports whether the node in group "player" moved
// and whether the current Camera3D sees it before and after moving.
using System.Globalization;
using System.Linq;
using Godot;

namespace ArtifactoryChecker;

public partial class CheckerProbe : Node
{
    private ulong _start;
    private int _stage;
    private Node3D _player;
    private Vector3 _p0, _p1, _p2;
    private string _problem;
    private string _unseenStart = "";

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
                _unseenStart = Unseen();
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
            GD.Print($"PROBE player_visible=false problem={_problem}");
            return;
        }
        Vector3 w = _p1 - _p0;
        Vector3 d = _p2 - _p1;
        bool differ = w.Length() > 0.1f && d.Length() > 0.1f
            && (w.Normalized() - d.Normalized()).Length() > 0.1f;
        string ws = w.Length().ToString("0.###", CultureInfo.InvariantCulture);
        string ds = d.Length().ToString("0.###", CultureInfo.InvariantCulture);
        GD.Print($"PROBE player_moves={(differ ? "true" : "false")} w={ws} d={ds}");
        string end = Unseen();
        bool seen = _unseenStart == "" && end == "";
        Camera3D cam = GetViewport().GetCamera3D();
        string camName = cam == null ? "none" : cam.Name.ToString();
        GD.Print($"PROBE player_visible={(seen ? "true" : "false")} camera={camName} start={Label(_unseenStart)} end={Label(end)}");
    }

    // A camera parented to the player and this close to it is a first-person view.
    private const float FirstPersonReach = 2f;

    private static string Label(string why) => why == "" ? "in_view" : why;

    // Why the player cannot be seen, or "" when it can. A first-person camera (parented to the
    // player, within FirstPersonReach) counts as seeing it. Otherwise a drawn mesh of the player must be inside the
    // camera's frustum at 16:9 with no collider in between. The frustum is computed here
    // because a headless viewport is 64x64, which would test a square frame.
    private string Unseen()
    {
        if (!Valid()) return "no_player";
        Camera3D cam = GetViewport().GetCamera3D();
        if (cam == null) return "no_camera";
        if (_player.IsAncestorOf(cam) && cam.GlobalPosition.DistanceTo(_player.GlobalPosition) <= FirstPersonReach) return "";
        var meshes = _player.FindChildren("*", "GeometryInstance3D", true, false)
            .OfType<GeometryInstance3D>().Where(g => g.IsVisibleInTree() && Drawn(g)).ToList();
        if (meshes.Count == 0) return "no_drawn_mesh";
        bool framed = false;
        foreach (var g in meshes)
        {
            Vector3 c = g.GlobalTransform * g.GetAabb().GetCenter();
            if (!InFrame(cam, c)) continue;
            framed = true;
            if (!Blocked(cam, c)) return "";
        }
        return framed ? "blocked" : "out_of_frame";
    }

    private static bool Drawn(GeometryInstance3D g)
    {
        if (g is not MeshInstance3D mi) return g.GetAabb().Size != Vector3.Zero;
        Rid rid = mi.Mesh?.GetRid() ?? default;
        return rid.IsValid && RenderingServer.MeshGetSurfaceCount(rid) > 0;
    }

    private static bool InFrame(Camera3D cam, Vector3 point)
    {
        Vector3 l = cam.GlobalTransform.AffineInverse() * point;
        float depth = -l.Z;
        if (depth < cam.Near || depth > cam.Far) return false;
        float half = cam.Projection == Camera3D.ProjectionType.Orthogonal
            ? cam.Size / 2f
            : depth * Mathf.Tan(Mathf.DegToRad(cam.Fov / 2f));
        const float aspect = 16f / 9f;
        bool keepHeight = cam.KeepAspect == Camera3D.KeepAspectEnum.Height;
        float hx = keepHeight ? half * aspect : half, hy = keepHeight ? half : half / aspect;
        return Mathf.Abs(l.X) <= hx && Mathf.Abs(l.Y) <= hy;
    }

    private bool Blocked(Camera3D cam, Vector3 point)
    {
        var ray = PhysicsRayQueryParameters3D.Create(cam.GlobalPosition, point);
        var own = new Godot.Collections.Array<Rid>();
        if (_player is CollisionObject3D self) own.Add(self.GetRid());
        foreach (var body in _player.FindChildren("*", "CollisionObject3D", true, false).OfType<CollisionObject3D>())
            own.Add(body.GetRid());
        ray.Exclude = own;
        return GetViewport().World3D.DirectSpaceState.IntersectRay(ray).Count > 0;
    }
}
