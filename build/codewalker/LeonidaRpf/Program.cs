// LeonidaRpf: edit GTA V Enhanced .rpf archives with CodeWalker.Core (by dexyfex), driven by Leonida.
//
//   LeonidaRpf.exe <gameDir> <ops.json>        -> one JSON object on stdout: {"ok":..., "results":[...]}
//
// gameDir is the folder with GTA5_Enhanced.exe: CodeWalker derives the archive keys from it (nothing is stored).
// ops.json is a list of operations, run in order in this one process (keys are loaded once):
//   {"op":"keys"}                                              check the keys load
//   {"op":"create", "rpf":ABS}                                  new empty RPF7 (OPEN) at ABS
//   {"op":"list",   "rpf":ABS}                                  every entry (nested archives included)
//   {"op":"extract","rpf":ABS, "entry":"a\\b.xml", "out":ABS}  write one entry's data to a file
//   {"op":"put",    "rpf":ABS, "entry":"x64\\data\\f.ymt", "src":ABS, "createArchives":true}
//   {"op":"delete", "rpf":ABS, "entry":"..."}                  a file, nested archive or folder (missing = ok, "deleted":false)
//   {"op":"hash",   "rpf":ABS, "entries":["..."]}              entry hashes (null = missing, plus "created": the first
//                                                              folder / nested archive on its path that is missing)
//   {"op":"hash",   "rpf":ABS, "all":true}                     every file entry, nested archives walked (not hashed)
//   {"op":"export", "rpf":ABS, "entry":"...", "out":ABS}       an entry backup that "put" imports back as the same entry
//                                                              (resources keep their RSC7 header and flags)
//   {"op":"ytd",    "rpf":ABS, "entry":"...\x.ytd", "src":ABS.dds, "texture":"name"}   replace one texture in a .ytd
//   {"op":"xml",    "rpf":ABS, "entry":"common\\data\\dlclist.xml",
//                   "edits":[{"type":"add|replace|remove", "xpath":"...", "append":"Last|First", "xml":"<Item/>"}]}
// Entry paths are relative to the archive root; a segment ending in .rpf steps into a nested archive. A relative "rpf",
// "src" or "out" path is relative to gameDir (not to the working folder the helper was started in).
// An entry hash is SHA-256 over its kind (resource/binary), a resource's system/graphics flags and its unpacked data:
// the same entry gives the same hash wherever it sits in the archive (whole-archive hashes change with the layout).
// Before anything is written, the archive (and its parents) is switched to OPEN encryption, exactly as CodeWalker's
// RPF Explorer does ("Loading by the game will require a mod loader such as OpenRPF.asi"). Leonida only ever points
// this at copies in the game's mods\ folder, and backs them up first.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Xml;
using CodeWalker.GameFiles;
using CodeWalker.Utils;

namespace LeonidaRpf
{
    internal static class Program
    {
        private static readonly JavaScriptSerializer Json = new JavaScriptSerializer { MaxJsonLength = int.MaxValue };
        private static readonly Dictionary<string, RpfFile> Open = new Dictionary<string, RpfFile>(StringComparer.OrdinalIgnoreCase);
        private static readonly List<string> ScanErrors = new List<string>();
        private static string GameDir = Directory.GetCurrentDirectory();

        /// A relative archive / file path is relative to the game folder, not to the helper's working folder.
        private static string Abs(string p)
        {
            return string.IsNullOrEmpty(p) ? p : Path.GetFullPath(Path.IsPathRooted(p) ? p : Path.Combine(GameDir, p));
        }

        private static int Main(string[] args)
        {
            var results = new List<object>();
            int index = -1;
            try
            {
                if (args.Length != 2) throw new ArgumentException("usage: LeonidaRpf.exe <gameDir> <ops.json>");
                string game = Path.GetFullPath(args[0]);
                GameDir = game;
                var ops = Json.Deserialize<List<Dictionary<string, object>>>(File.ReadAllText(args[1], Encoding.UTF8));
                bool keysLoaded = false;
                for (index = 0; index < ops.Count; index++)
                {
                    var op = ops[index];
                    string kind = Str(op, "op");
                    if (!keysLoaded && kind != "create")
                    {
                        if (!File.Exists(Path.Combine(game, "GTA5_Enhanced.exe")))
                            throw new FileNotFoundException("GTA5_Enhanced.exe not found in " + game);
                        GTA5Keys.LoadFromPath(game, true, null);
                        RpfManager.IsGen9 = true;
                        keysLoaded = true;
                    }
                    results.Add(Run(kind, op));
                }
                Write(new Dictionary<string, object> { ["ok"] = true, ["results"] = results, ["scanErrors"] = ScanErrors });
                return 0;
            }
            catch (Exception ex)
            {
                Write(new Dictionary<string, object>
                {
                    ["ok"] = false, ["error"] = ex.GetType().Name + ": " + ex.Message, ["op"] = index,
                    ["results"] = results, ["scanErrors"] = ScanErrors,
                });
                return 1;
            }
        }

        private static void Write(object o)
        {
            var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false));
            stdout.Write(Json.Serialize(o));
            stdout.Flush();
        }

        private static string Str(Dictionary<string, object> d, string key, string def = null)
        {
            return d.TryGetValue(key, out var v) && v != null ? Convert.ToString(v) : def;
        }

        private static object Run(string kind, Dictionary<string, object> op)
        {
            switch (kind)
            {
                case "keys":
                    return new Dictionary<string, object> { ["op"] = kind, ["ok"] = GTA5Keys.PC_AES_KEY != null };
                case "create": return Create(Abs(Str(op, "rpf")));
                case "list": return List(Abs(Str(op, "rpf")));
                case "extract": return Extract(Abs(Str(op, "rpf")), Str(op, "entry"), Abs(Str(op, "out")));
                case "put":
                    return Put(Abs(Str(op, "rpf")), Str(op, "entry"), Abs(Str(op, "src")),
                               !op.TryGetValue("createArchives", out var ca) || ca == null || Convert.ToBoolean(ca));
                case "delete": return Delete(Abs(Str(op, "rpf")), Str(op, "entry"));
                case "hash":
                    return Hash(Abs(Str(op, "rpf")), op.TryGetValue("entries", out var es) ? es as ArrayList : null,
                                op.TryGetValue("all", out var all) && all != null && Convert.ToBoolean(all));
                case "export": return Export(Abs(Str(op, "rpf")), Str(op, "entry"), Abs(Str(op, "out")));
                case "ytd": return YtdTexture(Abs(Str(op, "rpf")), Str(op, "entry"), Abs(Str(op, "src")), Str(op, "texture"));
                case "xml": return XmlEdit(Abs(Str(op, "rpf")), Str(op, "entry"), op["edits"] as ArrayList);
                default: throw new ArgumentException("unknown op " + kind);
            }
        }

        // ------------------------------------------------------------------ archive access
        private static RpfFile Root(string path)
        {
            path = Path.GetFullPath(path);
            if (Open.TryGetValue(path, out var rpf)) return rpf;
            if (!File.Exists(path)) throw new FileNotFoundException("archive not found: " + path);
            rpf = new RpfFile(path, Path.GetFileName(path));
            rpf.ScanStructure(null, e => ScanErrors.Add(e));
            if (rpf.Root == null) throw new InvalidDataException("could not read " + path + ": " + rpf.LastError);
            Open[path] = rpf;
            return rpf;
        }

        private static string[] Split(string entry)
        {
            return (entry ?? "").Replace('/', '\\').Split(new[] { '\\' }, StringSplitOptions.RemoveEmptyEntries);
        }

        /// Walk to the directory that should hold the last path segment. Creates folders / nested archives when asked.
        private static RpfDirectoryEntry Folder(RpfFile root, string[] parts, bool create)
        {
            RpfDirectoryEntry dir = root.Root;
            for (int i = 0; i < parts.Length - 1; i++)
            {
                string seg = parts[i].ToLowerInvariant();
                var sub = dir.Directories.FirstOrDefault(d => d.NameLower == seg);
                if (sub != null) { dir = sub; continue; }
                var file = dir.Files.FirstOrDefault(f => f.NameLower == seg);
                if (file != null && seg.EndsWith(".rpf"))
                {
                    var child = file.File.FindChildArchive(file);
                    if (child == null) throw new InvalidDataException(file.Path + " is not a readable archive");
                    dir = child.Root;
                    continue;
                }
                if (!create) return null;
                Writable(dir.File);
                if (seg.EndsWith(".rpf"))
                {
                    var created = RpfFile.CreateNew(dir, parts[i], RpfEncryption.OPEN);
                    dir = created.Root;
                }
                else
                {
                    dir = RpfFile.CreateDirectory(dir, parts[i]);
                }
            }
            return dir;
        }

        private static RpfFileEntry FindFile(RpfFile root, string entry)
        {
            var parts = Split(entry);
            if (parts.Length == 0) return null;
            var dir = Folder(root, parts, false);
            string name = parts[parts.Length - 1].ToLowerInvariant();
            return dir?.Files.FirstOrDefault(f => f.NameLower == name);
        }

        /// Switch the archive (and every archive it sits in) to OPEN encryption before writing, like RPF Explorer.
        private static void Writable(RpfFile file)
        {
            if (!RpfFile.EnsureValidEncryption(file, f => true, false))
                throw new InvalidOperationException("could not switch " + file.Path + " to OPEN encryption");
        }

        // ------------------------------------------------------------------ ops
        private static object Create(string path)
        {
            path = Path.GetFullPath(path);
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var rpf = RpfFile.CreateNew(Path.GetDirectoryName(path), path, RpfEncryption.OPEN);
            Open.Remove(path);
            return new Dictionary<string, object> { ["op"] = "create", ["rpf"] = path, ["size"] = new FileInfo(path).Length };
        }

        private static object List(string path)
        {
            var rpf = Root(path);
            var entries = new List<object>();
            Walk(rpf, "", entries);
            return new Dictionary<string, object>
            {
                ["op"] = "list", ["rpf"] = path, ["encryption"] = rpf.Encryption.ToString(), ["entries"] = entries,
            };
        }

        private static void Walk(RpfFile rpf, string prefix, List<object> outList)
        {
            if (rpf.AllEntries == null) return;
            string rootPath = rpf.Root.Path;
            foreach (var e in rpf.AllEntries)
            {
                if (!(e is RpfFileEntry fe)) continue;
                string rel = e.Path.Length > rootPath.Length ? e.Path.Substring(rootPath.Length + 1) : e.Path;
                outList.Add(new Dictionary<string, object>
                {
                    ["path"] = prefix + rel, ["size"] = fe.GetFileSize(),
                    ["type"] = fe is RpfResourceFileEntry ? "resource" : "binary",
                });
                if (fe.NameLower.EndsWith(".rpf"))
                {
                    var child = rpf.FindChildArchive(fe);
                    if (child != null) Walk(child, prefix + rel + "\\", outList);
                }
            }
        }

        private static object Extract(string path, string entry, string outPath)
        {
            var fe = FindFile(Root(path), entry) ?? throw new FileNotFoundException(entry + " not found in " + path);
            byte[] data = fe.File.ExtractFile(fe) ?? throw new InvalidDataException("could not extract " + entry);
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
            File.WriteAllBytes(outPath, data);
            return new Dictionary<string, object> { ["op"] = "extract", ["entry"] = entry, ["size"] = data.Length };
        }

        private static object Put(string path, string entry, string src, bool createArchives)
        {
            var root = Root(path);
            var parts = Split(entry);
            if (parts.Length == 0) throw new ArgumentException("empty entry path");
            var dir = Folder(root, parts, createArchives) ?? throw new DirectoryNotFoundException("folder for " + entry + " not found");
            Writable(dir.File);
            byte[] data = File.ReadAllBytes(src);
            var existed = dir.Files.Any(f => f.NameLower == parts[parts.Length - 1].ToLowerInvariant());
            var fe = RpfFile.CreateFile(dir, parts[parts.Length - 1], data, true);
            return new Dictionary<string, object>
            {
                ["op"] = "put", ["entry"] = entry, ["size"] = data.Length, ["replaced"] = existed, ["path"] = fe.Path,
            };
        }

        private static object Delete(string path, string entry)
        {
            var root = Root(path);
            RpfEntry target = FindFile(root, entry);
            if (target == null)
            {
                var parts = Split(entry);
                var parent = parts.Length > 0 ? Folder(root, parts, false) : null;
                string last = parts.Length > 0 ? parts[parts.Length - 1].ToLowerInvariant() : null;
                target = parent?.Directories.FirstOrDefault(d => d.NameLower == last);
            }
            if (target == null)
                return new Dictionary<string, object> { ["op"] = "delete", ["entry"] = entry, ["deleted"] = false };
            Writable(target.File);
            RpfFile.DeleteEntry(target);
            return new Dictionary<string, object> { ["op"] = "delete", ["entry"] = entry, ["deleted"] = true };
        }

        // ------------------------------------------------------------------ entry hashes and backups
        private static string EntryHash(RpfFileEntry fe)
        {
            byte[] data = fe.File.ExtractFile(fe) ?? new byte[0];
            using (var sha = SHA256.Create())
            {
                var head = new List<byte>();
                if (fe is RpfResourceFileEntry re)
                {
                    head.Add((byte)'R');
                    head.AddRange(BitConverter.GetBytes(re.SystemFlags));
                    head.AddRange(BitConverter.GetBytes(re.GraphicsFlags));
                }
                else head.Add((byte)'B');
                sha.TransformBlock(head.ToArray(), 0, head.Count, null, 0);
                sha.TransformFinalBlock(data, 0, data.Length);
                return BitConverter.ToString(sha.Hash).Replace("-", "").ToLowerInvariant();
            }
        }

        /// The first folder / nested archive on an entry's path that is missing ("a\b.rpf"), or null.
        private static string MissingContainer(RpfFile root, string[] parts)
        {
            RpfDirectoryEntry dir = root.Root;
            for (int i = 0; i < parts.Length - 1; i++)
            {
                string seg = parts[i].ToLowerInvariant();
                var sub = dir.Directories.FirstOrDefault(d => d.NameLower == seg);
                if (sub != null) { dir = sub; continue; }
                var file = dir.Files.FirstOrDefault(f => f.NameLower == seg);
                var child = file != null && seg.EndsWith(".rpf") ? file.File.FindChildArchive(file) : null;
                if (child != null) { dir = child.Root; continue; }
                return string.Join("\\", parts.Take(i + 1));
            }
            return null;
        }

        private static object Hash(string path, ArrayList entries, bool all)
        {
            var root = Root(path);
            var hashes = new Dictionary<string, object>();
            var created = new Dictionary<string, object>();
            if (all) HashAll(root, "", hashes);
            foreach (var e in entries ?? new ArrayList())
            {
                string entry = Convert.ToString(e);
                var fe = FindFile(root, entry);
                hashes[entry] = fe == null ? null : EntryHash(fe);
                if (fe == null) created[entry] = MissingContainer(root, Split(entry));
            }
            return new Dictionary<string, object>
            {
                ["op"] = "hash", ["rpf"] = path, ["hashes"] = hashes, ["created"] = created,
                ["encryption"] = root.Encryption.ToString(),
            };
        }

        private static void HashAll(RpfFile rpf, string prefix, Dictionary<string, object> outMap)
        {
            if (rpf.AllEntries == null) return;
            string rootPath = rpf.Root.Path;
            foreach (var e in rpf.AllEntries)
            {
                if (!(e is RpfFileEntry fe)) continue;
                string rel = e.Path.Length > rootPath.Length ? e.Path.Substring(rootPath.Length + 1) : e.Path;
                var child = fe.NameLower.EndsWith(".rpf") ? rpf.FindChildArchive(fe) : null;
                if (child != null) { HashAll(child, prefix + rel + "\\", outMap); continue; }
                outMap[prefix + rel] = EntryHash(fe);
            }
        }

        private static object Export(string path, string entry, string outPath)
        {
            var fe = FindFile(Root(path), entry);
            if (fe == null)
                return new Dictionary<string, object> { ["op"] = "export", ["entry"] = entry, ["exists"] = false };
            byte[] data = fe.File.ExtractFile(fe) ?? throw new InvalidDataException("could not extract " + entry);
            if (fe is RpfResourceFileEntry re)
                data = ResourceBuilder.AddResourceHeader(re, ResourceBuilder.Compress(data));
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath)));
            File.WriteAllBytes(outPath, data);
            return new Dictionary<string, object>
            {
                ["op"] = "export", ["entry"] = entry, ["exists"] = true, ["size"] = data.Length, ["hash"] = EntryHash(fe),
            };
        }

        // ------------------------------------------------------------------ textures (.ytd)
        private static object YtdTexture(string path, string entry, string src, string texture)
        {
            var root = Root(path);
            var fe = FindFile(root, entry) as RpfResourceFileEntry
                     ?? throw new FileNotFoundException(entry + " (a texture dictionary) not found in " + path);
            var ytd = new YtdFile();
            ytd.Load(fe.File.ExtractFile(fe), fe);
            var dict = ytd.TextureDict ?? throw new InvalidDataException(entry + " holds no textures");
            string name = string.IsNullOrEmpty(texture) ? Path.GetFileNameWithoutExtension(src) : texture;
            var tex = DDSIO.GetTexture(File.ReadAllBytes(src)) ?? throw new InvalidDataException(src + " is not a DDS texture");
            var list = dict.Textures?.data_items?.ToList() ?? new List<Texture>();
            int index = list.FindIndex(x => string.Equals(x.Name, name, StringComparison.OrdinalIgnoreCase));
            if (index < 0) throw new KeyNotFoundException("no texture " + name + " in " + entry);
            tex.Name = list[index].Name;
            tex.NameHash = JenkHash.GenHash(tex.Name.ToLowerInvariant());
            list[index] = tex;
            dict.BuildFromTextureList(list);
            byte[] outData = ytd.Save();
            Writable(fe.File);
            RpfFile.CreateFile(fe.Parent, fe.Name, outData, true);
            return new Dictionary<string, object>
            {
                ["op"] = "ytd", ["entry"] = entry, ["texture"] = tex.Name, ["width"] = (int)tex.Width, ["height"] = (int)tex.Height,
            };
        }

        // ------------------------------------------------------------------ xml edits (OpenIV .oiv semantics)
        private static object XmlEdit(string path, string entry, ArrayList edits)
        {
            var root = Root(path);
            var fe = FindFile(root, entry) ?? throw new FileNotFoundException(entry + " not found in " + path);
            byte[] data = fe.File.ExtractFile(fe);
            bool bom = data.Length >= 3 && data[0] == 0xEF && data[1] == 0xBB && data[2] == 0xBF;
            string text = new UTF8Encoding(false).GetString(data, bom ? 3 : 0, data.Length - (bom ? 3 : 0));
            if (text.StartsWith("RBF0")) throw new InvalidDataException(entry + " is binary (RBF) XML; not supported");
            var doc = new XmlDocument { PreserveWhitespace = true };
            doc.LoadXml(text);
            var counts = new List<object>();
            foreach (Dictionary<string, object> ed in edits)
            {
                string type = Str(ed, "type"), xpath = Str(ed, "xpath"), xml = Str(ed, "xml", "");
                var nodes = doc.SelectNodes(xpath).Cast<XmlNode>().ToList();
                foreach (var node in nodes)
                {
                    switch (type)
                    {
                        case "add":
                            var frag = doc.CreateDocumentFragment();
                            frag.InnerXml = xml;
                            if (string.Equals(Str(ed, "append", "Last"), "First", StringComparison.OrdinalIgnoreCase))
                                node.PrependChild(frag);
                            else
                                node.AppendChild(frag);
                            break;
                        case "replace":
                            var rep = doc.CreateDocumentFragment();
                            rep.InnerXml = xml;
                            if (node is XmlAttribute attr) { attr.Value = rep.InnerText; break; }
                            node.ParentNode.ReplaceChild(rep, node);
                            break;
                        case "remove":
                            if (node is XmlAttribute a2) a2.OwnerElement.RemoveAttributeNode(a2);
                            else node.ParentNode?.RemoveChild(node);
                            break;
                        default: throw new ArgumentException("unknown xml edit " + type);
                    }
                }
                counts.Add(nodes.Count);
            }
            string outText = doc.OuterXml;
            var bytes = new List<byte>();
            if (bom) bytes.AddRange(new byte[] { 0xEF, 0xBB, 0xBF });
            bytes.AddRange(new UTF8Encoding(false).GetBytes(outText));
            var dir = fe.Parent;
            string name = fe.Name;
            Writable(dir.File);
            RpfFile.CreateFile(dir, name, bytes.ToArray(), true);
            return new Dictionary<string, object> { ["op"] = "xml", ["entry"] = entry, ["matched"] = counts };
        }
    }
}
