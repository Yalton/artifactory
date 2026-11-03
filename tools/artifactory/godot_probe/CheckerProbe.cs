// Injected by the Artifactory Godot checker into a copy of the trial project.
// Presses W, then D, and reports whether the node in group "player" moved
// whether the current Camera3D sees it before and after moving, and whether drawn
// geometry surrounds its start point (a floor and four walls).
// With ARTIFACTORY_PROBE_MODE=lantern the main scene is a title screen, so the probe
// loads the rooms itself: the move/visible check runs in the courtyard, then every room
// must hold a player, then `interact` next to the keeper in the hall must show the dialogue.
// Lantern mode does not report room_present: its `rooms` check covers the level.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
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
    private string _roomMissing = "";
    private bool _lantern;

    public override void _Ready()
    {
        ProcessMode = ProcessModeEnum.Always;
        _start = Time.GetTicksMsec();
        _lantern = OS.GetEnvironment("ARTIFACTORY_PROBE_MODE") == "lantern";
        if (_lantern)
        {
            _stage = -1;  // the timed stages below never run
            RunLantern();
        }
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
                _roomMissing = RoomMissing();
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

    // --- lantern mode ---------------------------------------------------------

    private const string Courtyard = "res://rooms/courtyard.tscn";
    private const string Hall = "res://rooms/hall.tscn";
    private static readonly string[] Rooms = { "courtyard", "hall", "tower" };
    private const float KeeperDistance = 1f;
    private const ulong SceneChangeMs = 5000, DialogueWaitMs = 2000;

    private async void RunLantern()
    {
        try
        {
            await Frames(1);
            if (await ChangeTo(Courtyard))
            {
                await Seconds(1.0);
                FindPlayer();
                if (_player != null) _p0 = _player.GlobalPosition;
                _unseenStart = Unseen();
                SendKey(Key.W, true);
                await Seconds(1.0);
                SendKey(Key.W, false);
                if (Valid()) _p1 = _player.GlobalPosition;
                SendKey(Key.D, true);
                await Seconds(1.0);
                SendKey(Key.D, false);
                if (Valid()) _p2 = _player.GlobalPosition;
            }
            else
            {
                _player = null;
                _problem = "no_room";
            }
            Report();

            var missing = new List<string>();
            foreach (string room in Rooms)
            {
                if (!await ChangeTo($"res://rooms/{room}.tscn") || GetTree().GetNodesInGroup("player").Count == 0)
                    missing.Add(room);
            }
            GD.Print($"PROBE rooms={Bool(missing.Count == 0)} missing={(missing.Count == 0 ? "none" : string.Join(",", missing))}");

            string problem = await Dialogue();
            GD.Print($"PROBE dialogue={Bool(problem == null)} problem={problem ?? "none"}");
        }
        catch (Exception e)
        {
            GD.Print($"PROBE lantern_error={e.GetType().Name}: {e.Message}");
        }
        finally
        {
            GetTree().Quit();
        }
    }

    private static string Bool(bool b) => b ? "true" : "false";

    // Null when the dialogue showed, else why not.
    private async Task<string> Dialogue()
    {
        if (!await ChangeTo(Hall)) return "no_room";
        FindPlayer();
        if (!Valid()) return "no_player";
        Node3D keeper = GetTree().GetNodesInGroup("keeper").OfType<Node3D>().FirstOrDefault();
        if (keeper == null) return "no_keeper";
        if (!InputMap.HasAction("interact")) return "no_action";

        // Stand 1 m in front of the keeper (its +Z, the model front), level with where the player was, facing it.
        Vector3 front = keeper.GlobalBasis.Z with { Y = 0 };
        front = front.LengthSquared() < 1e-6f ? Vector3.Back : front.Normalized();
        Vector3 at = keeper.GlobalPosition + front * KeeperDistance;
        _player.GlobalPosition = at with { Y = _player.GlobalPosition.Y };
        Vector3 look = keeper.GlobalPosition with { Y = _player.GlobalPosition.Y };
        if (look.DistanceTo(_player.GlobalPosition) > 1e-3f) _player.LookAt(look, Vector3.Up);
        if (_player is CharacterBody3D body) body.Velocity = Vector3.Zero;

        // Enough steps for an Area3D around the keeper to report the overlap.
        await PhysicsFrames(5);
        // The dialogue must open because of `interact`, so one already showing does not count.
        if (DialogueShown()) return "shown_before_interact";
        Input.ParseInputEvent(new InputEventAction { Action = "interact", Pressed = true });
        await PhysicsFrames(1);
        Input.ParseInputEvent(new InputEventAction { Action = "interact", Pressed = false });
        ulong deadline = Time.GetTicksMsec() + DialogueWaitMs;
        while (Time.GetTicksMsec() <= deadline)
        {
            if (DialogueShown()) return null;
            await Frames(1);
        }
        return DialogueShown() ? null : "not_shown";
    }

    // A CanvasLayer or plain Node says nothing by itself (a layer is visible by default):
    // it counts only when it is visible and some CanvasItem under it is drawn.
    private bool DialogueShown() => GetTree().GetNodesInGroup("dialogue").Any(n => n switch
    {
        CanvasItem c => c.IsVisibleInTree(),
        Node3D n3 => n3.IsVisibleInTree(),
        CanvasLayer l => l.Visible && AnyDrawnCanvasItem(l),
        _ => AnyDrawnCanvasItem(n),
    });

    private static bool AnyDrawnCanvasItem(Node n) =>
        n.FindChildren("*", "CanvasItem", true, false).OfType<CanvasItem>().Any(c => c.IsVisibleInTree());

    // Change scene and wait until the new instance of `path` is current, plus one frame.
    // A missing room is a probe failure, so it is never handed to the loader.
    private async Task<bool> ChangeTo(string path)
    {
        if (!ResourceLoader.Exists(path)) return false;
        Node old = GetTree().CurrentScene;
        ulong oldId = old == null ? 0 : old.GetInstanceId();
        if (GetTree().ChangeSceneToFile(path) != Error.Ok) return false;
        ulong deadline = Time.GetTicksMsec() + SceneChangeMs;
        while (true)
        {
            Node cur = GetTree().CurrentScene;
            if (cur != null && cur.GetInstanceId() != oldId && cur.SceneFilePath == path) break;
            if (Time.GetTicksMsec() > deadline) return false;
            await Frames(1);
        }
        await Frames(1);
        return true;
    }

    private async Task Frames(int n)
    {
        for (int i = 0; i < n; i++) await ToSignal(GetTree(), SceneTree.SignalName.ProcessFrame);
    }

    private async Task PhysicsFrames(int n)
    {
        for (int i = 0; i < n; i++) await ToSignal(GetTree(), SceneTree.SignalName.PhysicsFrame);
    }

    private async Task Seconds(double s)
    {
        await ToSignal(GetTree().CreateTimer(s, true), SceneTreeTimer.SignalName.Timeout);
    }

    // --- shared --------------------------------------------------------------

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
            if (!_lantern) GD.Print($"PROBE room_present=false problem={_problem}");
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
        if (_lantern) return;
        GD.Print(_roomMissing == "" ? "PROBE room_present=true"
            : $"PROBE room_present=false missing={_roomMissing}");
    }

    // How far below the player a floor, and how far around it a wall, may be.
    private const float FloorReach = 10f, WallReach = 100f;

    // The directions from the player's start with no drawn geometry, comma-separated, or "" when
    // a floor lies below and a wall on all four sides. Geometry counts if the ray meets its box
    // or starts inside it, so a room built as one mesh around the player also counts.
    private string RoomMissing()
    {
        if (!Valid()) return "no_player";
        Vector3 o = _player.GlobalPosition;
        var boxes = SceneBoxes(null);
        (string name, Vector3 dir)[] dirs =
        {
            ("down", Vector3.Down * FloorReach), ("+x", Vector3.Right * WallReach), ("-x", Vector3.Left * WallReach),
            ("+z", Vector3.Back * WallReach), ("-z", Vector3.Forward * WallReach),
        };
        return string.Join(",", dirs.Where(d => !boxes.Any(b => b.HasPoint(o) || b.IntersectsSegment(o, o + d.dir)))
            .Select(d => d.name));
    }

    // World-space boxes of every drawn mesh outside the player (and outside the camera, if given).
    private List<Aabb> SceneBoxes(Camera3D cam) =>
        GetTree().Root.FindChildren("*", "GeometryInstance3D", true, false).OfType<GeometryInstance3D>()
            .Where(g => g.IsVisibleInTree() && Drawn(g) && g != _player && !_player.IsAncestorOf(g)
                && (cam == null || !cam.IsAncestorOf(g)))
            .Select(g => g.GlobalTransform * g.GetAabb()).ToList();

    // A camera parented to the player and this close to it is a first-person view.
    private const float FirstPersonReach = 2f;

    private static string Label(string why) => why == "" ? "in_view" : why;

    // Why the player cannot be seen, or "" when it can. A first-person camera (parented to the
    // player, within FirstPersonReach) counts as seeing it. Otherwise a drawn mesh of the player must be inside the
    // camera's frustum at 16:9 with nothing in between: no collider, and no drawn mesh whose box
    // the sight line enters from outside. The centre and the top of each mesh are tried. The frustum is computed here
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
        var boxes = SceneBoxes(cam).Where(b => !b.HasPoint(cam.GlobalPosition)).ToList();
        bool framed = false;
        foreach (var g in meshes)
        {
            Aabb box = g.GetAabb();
            Vector3 centre = box.GetCenter();
            foreach (Vector3 local in new[] { centre, centre with { Y = box.Position.Y + box.Size.Y * 0.9f } })
            {
                Vector3 c = g.GlobalTransform * local;
                if (!InFrame(cam, c)) continue;
                framed = true;
                if (!Blocked(cam, c) && !boxes.Any(b => b.IntersectsSegment(cam.GlobalPosition, c))) return "";
            }
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
