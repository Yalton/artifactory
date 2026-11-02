using Godot;

namespace TrialGame;

// Hand-written settings store that duplicates a kit's job.
public partial class SettingsStore : Node
{
    public void Save()
    {
        var cfg = new ConfigFile();
        cfg.Save("user://settings.cfg");
    }
}
