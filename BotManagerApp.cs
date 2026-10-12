using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Net.Sockets;
using System.Security.Principal;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace JMComicBotManager
{
    public class BotControlConfig
    {
        public string access_mode { get; set; }
        public List<string> allowed_users { get; set; }
        public List<string> blocked_users { get; set; }
        public List<string> allowed_groups { get; set; }
        public List<string> blocked_groups { get; set; }
        public Dictionary<string, bool> features { get; set; }
        public Dictionary<string, Dictionary<string, bool>> user_features { get; set; }
    }

    public class PythonCommand
    {
        public string FileName;
        public string PrefixArgs;
        public string DisplayName;
    }

    public class ManagedProcess
    {
        public string Name;
        public Process Process;
        public string LogFile;
        public DateTime? StartedAt;
    }

    public class MainForm : Form
    {
        private readonly string root;
        private readonly string controlFile;
        private readonly string envFile;
        private readonly string logDir;
        private readonly JavaScriptSerializer serializer = new JavaScriptSerializer();
        private readonly Dictionary<string, string> featureLabels = new Dictionary<string, string>();
        private readonly Dictionary<string, CheckBox> featureChecks = new Dictionary<string, CheckBox>();
        private readonly Dictionary<string, CheckBox> userFeatureChecks = new Dictionary<string, CheckBox>();
        private readonly Dictionary<string, CheckBox> runtimeUserFeatureChecks = new Dictionary<string, CheckBox>();
        private readonly Dictionary<TabPage, Button> navButtons = new Dictionary<TabPage, Button>();
        private readonly Dictionary<string, ManagedProcess> processes = new Dictionary<string, ManagedProcess>();
        private BotControlConfig config;
        private bool updatingUi;
        private string selectedFeatureUser = "";
        private DateTime lastConfigWriteUtc = DateTime.MinValue;

        private Label nonebotStatus;
        private Label napcatStatus;
        private Label portStatus;
        private Label pythonStatus;
        private Label messageLabel;
        private RadioButton accessAllRadio;
        private RadioButton accessAllowlistRadio;
        private ListBox allowedUsersList;
        private ListBox blockedUsersList;
        private ListBox allowedGroupsList;
        private ListBox blockedGroupsList;
        private ListBox quickAllowedUsersList;
        private ListBox quickBlockedUsersList;
        private TextBox quickUserInput;
        private RadioButton quickAccessAllRadio;
        private RadioButton quickAccessAllowlistRadio;
        private TextBox allowedUsersInput;
        private TextBox blockedUsersInput;
        private TextBox allowedGroupsInput;
        private TextBox blockedGroupsInput;
        private ComboBox logTargetCombo;
        private TextBox logBox;
        private TextBox featureUserInput;
        private Label featureUserLabel;
        private ListBox featureUsersList;
        private TextBox runtimeFeatureUserInput;
        private Label runtimeFeatureUserLabel;
        private TabControl mainTabs;

        public MainForm()
        {
            root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
            controlFile = Path.Combine(root, "plugins", "bot_control.json");
            envFile = Path.Combine(root, ".env");
            logDir = Path.Combine(root, "logs", "manager_app");

            Directory.CreateDirectory(logDir);
            BuildFeatureLabels();
            LoadConfig();
            BuildUi();
            RefreshAll();
        }

        private void BuildFeatureLabels()
        {
            featureLabels["jm_image"] = "JM 图片发送";
            featureLabels["jm_file"] = "JM 加密压缩包";
            featureLabels["jm_cover"] = "JM 封面";
            featureLabels["jm_search"] = "JM 关键词搜索";
            featureLabels["jm_recommend"] = "JM 随机推荐";
            featureLabels["pixiv_recommend"] = "Pixiv 推荐/订阅推送";
            featureLabels["pixiv_search"] = "Pixiv TAG/PID 搜图";
            featureLabels["pixiv_random"] = "Pixiv 来点图";
            featureLabels["pixiv_rating"] = "评分偏好系统";
        }

        private BotControlConfig DefaultConfig()
        {
            BotControlConfig data = new BotControlConfig();
            data.access_mode = "all";
            data.allowed_users = new List<string>();
            data.blocked_users = new List<string>();
            data.allowed_groups = new List<string>();
            data.blocked_groups = new List<string>();
            data.features = new Dictionary<string, bool>();
            data.user_features = new Dictionary<string, Dictionary<string, bool>>();
            foreach (string key in featureLabels.Keys)
            {
                data.features[key] = true;
            }
            return data;
        }

        private void LoadConfig()
        {
            LoadConfigFromDisk(true);
        }

        private void LoadConfigFromDisk(bool saveAfterLoad)
        {
            config = DefaultConfig();
            try
            {
                if (File.Exists(controlFile))
                {
                    string json = File.ReadAllText(controlFile, Encoding.UTF8);
                    BotControlConfig loaded = serializer.Deserialize<BotControlConfig>(json);
                    if (loaded != null)
                    {
                        MergeConfig(loaded);
                    }
                }
                if (saveAfterLoad)
                {
                    SaveConfig();
                }
                else
                {
                    UpdateConfigWriteTime();
                }
            }
            catch (Exception ex)
            {
                WriteLog("manager", "读取配置失败：" + ex.Message);
            }
        }

        private void MergeConfig(BotControlConfig loaded)
        {
            config.access_mode = loaded.access_mode == "allowlist" ? "allowlist" : "all";
            config.allowed_users = CleanList(loaded.allowed_users);
            config.blocked_users = CleanList(loaded.blocked_users);
            config.allowed_groups = CleanList(loaded.allowed_groups);
            config.blocked_groups = CleanList(loaded.blocked_groups);
            config.user_features = CleanUserFeatures(loaded.user_features);

            if (loaded.features != null)
            {
                foreach (string key in featureLabels.Keys)
                {
                    if (loaded.features.ContainsKey(key))
                    {
                        config.features[key] = loaded.features[key];
                    }
                }
            }
        }

        private Dictionary<string, Dictionary<string, bool>> CleanUserFeatures(Dictionary<string, Dictionary<string, bool>> values)
        {
            Dictionary<string, Dictionary<string, bool>> result = new Dictionary<string, Dictionary<string, bool>>();
            if (values == null)
            {
                return result;
            }

            foreach (KeyValuePair<string, Dictionary<string, bool>> item in values)
            {
                string userId = (item.Key ?? "").Trim();
                if (userId.Length == 0 || item.Value == null)
                {
                    continue;
                }

                Dictionary<string, bool> features = new Dictionary<string, bool>();
                foreach (string key in featureLabels.Keys)
                {
                    if (item.Value.ContainsKey(key))
                    {
                        features[key] = item.Value[key];
                    }
                }
                if (features.Count > 0)
                {
                    result[userId] = features;
                }
            }
            return result;
        }

        private List<string> CleanList(List<string> values)
        {
            List<string> result = new List<string>();
            if (values == null)
            {
                return result;
            }
            foreach (string value in values)
            {
                string item = (value ?? "").Trim();
                if (item.Length > 0 && !result.Contains(item))
                {
                    result.Add(item);
                }
            }
            return result;
        }

        private void SaveConfig()
        {
            Directory.CreateDirectory(Path.GetDirectoryName(controlFile));
            string json = serializer.Serialize(config);
            File.WriteAllText(controlFile, PrettyJson(json), new UTF8Encoding(false));
            UpdateConfigWriteTime();
        }

        private void UpdateConfigWriteTime()
        {
            try
            {
                if (File.Exists(controlFile))
                {
                    lastConfigWriteUtc = File.GetLastWriteTimeUtc(controlFile);
                }
            }
            catch { }
        }

        private void ReloadConfigIfChanged()
        {
            try
            {
                if (!File.Exists(controlFile))
                {
                    return;
                }

                DateTime currentWrite = File.GetLastWriteTimeUtc(controlFile);
                if (currentWrite <= lastConfigWriteUtc)
                {
                    return;
                }

                string previousUser = selectedFeatureUser;
                LoadConfigFromDisk(false);
                selectedFeatureUser = previousUser;
            }
            catch (Exception ex)
            {
                WriteLog("manager", "刷新配置失败：" + ex.Message);
            }
        }

        private string PrettyJson(string json)
        {
            StringBuilder output = new StringBuilder();
            int indent = 0;
            bool inString = false;
            for (int i = 0; i < json.Length; i++)
            {
                char c = json[i];
                if (c == '"' && (i == 0 || json[i - 1] != '\\'))
                {
                    inString = !inString;
                }

                if (!inString && (c == '{' || c == '['))
                {
                    output.Append(c);
                    output.AppendLine();
                    indent++;
                    output.Append(new string(' ', indent * 2));
                }
                else if (!inString && (c == '}' || c == ']'))
                {
                    output.AppendLine();
                    indent--;
                    output.Append(new string(' ', Math.Max(0, indent) * 2));
                    output.Append(c);
                }
                else if (!inString && c == ',')
                {
                    output.Append(c);
                    output.AppendLine();
                    output.Append(new string(' ', indent * 2));
                }
                else if (!inString && c == ':')
                {
                    output.Append(": ");
                }
                else
                {
                    output.Append(c);
                }
            }
            return output.ToString();
        }

        private void BuildUi()
        {
            Text = "JM Comic Bot 管理程序";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(1160, 760);
            Size = new Size(1280, 840);
            Font = new Font("Microsoft YaHei UI", 9F);
            BackColor = Color.FromArgb(244, 246, 248);

            TableLayoutPanel rootLayout = new TableLayoutPanel();
            rootLayout.Dock = DockStyle.Fill;
            rootLayout.ColumnCount = 1;
            rootLayout.RowCount = 2;
            rootLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 74));
            rootLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            Controls.Add(rootLayout);

            Panel header = new Panel();
            header.Dock = DockStyle.Fill;
            header.BackColor = Color.FromArgb(24, 36, 43);
            rootLayout.Controls.Add(header, 0, 0);

            Label title = new Label();
            title.Text = "JM Comic Bot 管理程序";
            title.ForeColor = Color.White;
            title.Font = new Font(Font.FontFamily, 16F, FontStyle.Bold);
            title.AutoSize = true;
            title.Location = new Point(22, 16);
            header.Controls.Add(title);

            Label subtitle = new Label();
            subtitle.Text = "启动机器人、管理使用人员、开关功能、查看日志";
            subtitle.ForeColor = Color.FromArgb(190, 208, 214);
            subtitle.AutoSize = true;
            subtitle.Location = new Point(24, 45);
            header.Controls.Add(subtitle);

            messageLabel = new Label();
            messageLabel.Text = "就绪";
            messageLabel.ForeColor = Color.FromArgb(190, 208, 214);
            messageLabel.AutoSize = false;
            messageLabel.TextAlign = ContentAlignment.MiddleRight;
            messageLabel.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            messageLabel.Location = new Point(600, 22);
            messageLabel.Size = new Size(480, 30);
            header.Controls.Add(messageLabel);

            Panel shell = new Panel();
            shell.Dock = DockStyle.Fill;
            rootLayout.Controls.Add(shell, 0, 1);

            Panel nav = new Panel();
            nav.Dock = DockStyle.Top;
            nav.Height = 52;
            nav.BackColor = Color.FromArgb(232, 238, 242);
            shell.Controls.Add(nav);

            FlowLayoutPanel navFlow = new FlowLayoutPanel();
            navFlow.Dock = DockStyle.Fill;
            navFlow.Padding = new Padding(16, 8, 16, 6);
            navFlow.WrapContents = false;
            nav.Controls.Add(navFlow);

            mainTabs = new TabControl();
            mainTabs.Dock = DockStyle.Fill;
            mainTabs.Padding = new Point(16, 7);
            mainTabs.Appearance = TabAppearance.FlatButtons;
            mainTabs.SizeMode = TabSizeMode.Fixed;
            mainTabs.ItemSize = new Size(1, 1);
            mainTabs.SelectedIndexChanged += delegate { UpdateNavButtons(); };
            shell.Controls.Add(mainTabs);
            mainTabs.BringToFront();
            nav.BringToFront();

            TabPage runtimePage = new TabPage("运行控制");
            TabPage accessPage = new TabPage("使用人员");
            TabPage userFeaturePage = new TabPage("单人功能");
            TabPage featurePage = new TabPage("功能开关");
            TabPage logPage = new TabPage("日志");
            mainTabs.TabPages.Add(runtimePage);
            mainTabs.TabPages.Add(accessPage);
            mainTabs.TabPages.Add(userFeaturePage);
            mainTabs.TabPages.Add(featurePage);
            mainTabs.TabPages.Add(logPage);

            AddNavButton(navFlow, "运行控制", runtimePage);
            AddNavButton(navFlow, "使用人员", accessPage);
            AddNavButton(navFlow, "单人功能", userFeaturePage);
            AddNavButton(navFlow, "功能开关", featurePage);
            AddNavButton(navFlow, "日志", logPage);
            AddManualRefreshButton(navFlow);

            BuildRuntimePage(runtimePage);
            BuildAccessPage(accessPage);
            BuildUserFeaturePage(userFeaturePage);
            BuildFeaturePage(featurePage);
            BuildLogPage(logPage);
            UpdateNavButtons();
        }

        private void AddNavButton(FlowLayoutPanel navFlow, string text, TabPage page)
        {
            Button button = new Button();
            button.Text = text;
            button.Width = 122;
            button.Height = 34;
            button.Margin = new Padding(4, 0, 4, 0);
            button.Click += delegate
            {
                mainTabs.SelectedTab = page;
                UpdateNavButtons();
            };
            StyleButton(button);
            navButtons[page] = button;
            navFlow.Controls.Add(button);
        }

        private void AddManualRefreshButton(FlowLayoutPanel navFlow)
        {
            Button button = new Button();
            button.Text = "⟳ 手动刷新";
            button.Width = 118;
            button.Height = 34;
            button.Margin = new Padding(14, 0, 4, 0);
            button.Click += delegate
            {
                RefreshAll();
                SetMessage("已手动刷新。");
            };
            StyleButton(button, primary: true);
            navFlow.Controls.Add(button);
        }

        private void UpdateNavButtons()
        {
            if (mainTabs == null) return;
            foreach (KeyValuePair<TabPage, Button> item in navButtons)
            {
                bool selected = item.Key == mainTabs.SelectedTab;
                item.Value.BackColor = selected ? Color.FromArgb(15, 118, 110) : Color.White;
                item.Value.ForeColor = selected ? Color.White : Color.FromArgb(23, 32, 38);
                item.Value.FlatStyle = FlatStyle.Flat;
                item.Value.FlatAppearance.BorderColor = selected ? Color.FromArgb(15, 118, 110) : Color.FromArgb(190, 202, 210);
            }
        }

        private void StyleButton(Button button, bool primary = false, bool danger = false)
        {
            button.FlatStyle = FlatStyle.Flat;
            button.FlatAppearance.BorderSize = 1;
            button.Cursor = Cursors.Hand;
            button.Font = new Font(Font.FontFamily, 9F);

            if (primary)
            {
                button.BackColor = Color.FromArgb(15, 118, 110);
                button.ForeColor = Color.White;
                button.FlatAppearance.BorderColor = Color.FromArgb(13, 104, 97);
                button.FlatAppearance.MouseOverBackColor = Color.FromArgb(18, 140, 130);
                button.FlatAppearance.MouseDownBackColor = Color.FromArgb(11, 92, 86);
            }
            else if (danger)
            {
                button.BackColor = Color.White;
                button.ForeColor = Color.FromArgb(190, 60, 60);
                button.FlatAppearance.BorderColor = Color.FromArgb(220, 160, 160);
                button.FlatAppearance.MouseOverBackColor = Color.FromArgb(252, 236, 236);
                button.FlatAppearance.MouseDownBackColor = Color.FromArgb(248, 220, 220);
            }
            else
            {
                button.BackColor = Color.White;
                button.ForeColor = Color.FromArgb(23, 32, 38);
                button.FlatAppearance.BorderColor = Color.FromArgb(188, 200, 208);
                button.FlatAppearance.MouseOverBackColor = Color.FromArgb(236, 245, 244);
                button.FlatAppearance.MouseDownBackColor = Color.FromArgb(224, 236, 235);
            }
        }

        private Button MakeButton(string text, EventHandler click)
        {
            Button button = new Button();
            button.Text = text;
            button.Dock = DockStyle.Fill;
            button.Height = 34;
            button.Margin = new Padding(4);
            button.Click += click;
            StyleButton(button);
            return button;
        }

        private void AddActionButton(TableLayoutPanel parent, string text, EventHandler click, int column, int row, bool primary = false, bool danger = false)
        {
            Button button = MakeButton(text, click);
            if (primary || danger)
            {
                StyleButton(button, primary: primary, danger: danger);
            }
            parent.Controls.Add(button, column, row);
        }

        private void BuildRuntimePage(TabPage page)
        {
            page.BackColor = BackColor;

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 2;
            layout.RowCount = 3;
            layout.Padding = new Padding(18);
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 245));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 238));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.Controls.Add(layout);

            GroupBox statusBox = new GroupBox();
            statusBox.Text = "状态";
            statusBox.Dock = DockStyle.Fill;
            statusBox.Padding = new Padding(14);
            layout.Controls.Add(statusBox, 0, 0);

            TableLayoutPanel statusLayout = new TableLayoutPanel();
            statusLayout.Dock = DockStyle.Fill;
            statusLayout.RowCount = 4;
            statusLayout.ColumnCount = 1;
            statusBox.Controls.Add(statusLayout);

            nonebotStatus = MakeStatusLabel("NoneBot：检测中");
            napcatStatus = MakeStatusLabel("NapCat：检测中");
            portStatus = MakeStatusLabel("OneBot 端口：检测中");
            pythonStatus = MakeStatusLabel("Python：检测中");
            statusLayout.Controls.Add(nonebotStatus);
            statusLayout.Controls.Add(napcatStatus);
            statusLayout.Controls.Add(portStatus);
            statusLayout.Controls.Add(pythonStatus);

            GroupBox actionsBox = new GroupBox();
            actionsBox.Text = "操作";
            actionsBox.Dock = DockStyle.Fill;
            actionsBox.Padding = new Padding(14);
            layout.Controls.Add(actionsBox, 1, 0);

            TableLayoutPanel actions = new TableLayoutPanel();
            actions.Dock = DockStyle.Fill;
            actions.ColumnCount = 2;
            actions.RowCount = 5;
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            actions.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            for (int i = 0; i < 5; i++)
            {
                actions.RowStyles.Add(new RowStyle(SizeType.Percent, 20));
            }
            actionsBox.Controls.Add(actions);

            AddActionButton(actions, "启动全部", delegate { StartAll(); }, 0, 0, primary: true);
            AddActionButton(actions, "停止全部", delegate { StopAll(); }, 1, 0, danger: true);
            AddActionButton(actions, "启动 NoneBot", delegate { StartNoneBot(); }, 0, 1, primary: true);
            AddActionButton(actions, "停止 NoneBot", delegate { StopProcess("nonebot"); }, 1, 1, danger: true);
            AddActionButton(actions, "启动 NapCat", delegate { StartNapCat(); }, 0, 2, primary: true);
            AddActionButton(actions, "停止 NapCat", delegate { StopProcess("napcat"); }, 1, 2, danger: true);
            actions.Controls.Add(MakeButton("安装/检查依赖", delegate { InstallDependencies(); }), 0, 3);
            actions.Controls.Add(MakeButton("安装/修复 NapCat", delegate { SetupNapCat(); }), 1, 3);
            actions.Controls.Add(MakeButton("清理缓存文件", delegate { CleanCacheFiles(); }), 0, 4);
            AddActionButton(actions, "更新重启 NoneBot", delegate { UpdateRestartNoneBot(); }, 1, 4, primary: true);

            GroupBox quickAccessBox = new GroupBox();
            quickAccessBox.Text = "QQ 使用人员管理";
            quickAccessBox.Dock = DockStyle.Fill;
            quickAccessBox.Padding = new Padding(14);
            layout.SetColumnSpan(quickAccessBox, 2);
            layout.Controls.Add(quickAccessBox, 0, 1);
            BuildQuickAccessEditor(quickAccessBox);

            GroupBox runtimeFeatureBox = new GroupBox();
            runtimeFeatureBox.Text = "单个 QQ 功能管理";
            runtimeFeatureBox.Dock = DockStyle.Fill;
            runtimeFeatureBox.Padding = new Padding(14);
            layout.SetColumnSpan(runtimeFeatureBox, 2);
            layout.Controls.Add(runtimeFeatureBox, 0, 2);
            BuildRuntimeUserFeatureEditor(runtimeFeatureBox);
        }

        private void BuildRuntimeUserFeatureEditor(GroupBox parent)
        {
            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.RowCount = 2;
            layout.ColumnCount = 1;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            parent.Controls.Add(layout);

            FlowLayoutPanel tools = new FlowLayoutPanel();
            tools.Dock = DockStyle.Fill;
            tools.WrapContents = false;
            layout.Controls.Add(tools, 0, 0);

            runtimeFeatureUserInput = new TextBox();
            runtimeFeatureUserInput.Width = 170;
            runtimeFeatureUserInput.Margin = new Padding(4, 8, 6, 4);
            runtimeFeatureUserInput.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Enter)
                {
                    SelectFeatureUser(runtimeFeatureUserInput.Text);
                    e.SuppressKeyPress = true;
                }
            };
            tools.Controls.Add(runtimeFeatureUserInput);

            Button loadUser = new Button();
            loadUser.Text = "载入/新增";
            loadUser.Width = 90;
            loadUser.Height = 30;
            loadUser.Margin = new Padding(4, 6, 4, 4);
            loadUser.Click += delegate { SelectFeatureUser(runtimeFeatureUserInput.Text); };
            tools.Controls.Add(loadUser);

            Button allowAll = new Button();
            allowAll.Text = "全部开启";
            allowAll.Width = 90;
            allowAll.Height = 30;
            allowAll.Margin = new Padding(4, 6, 4, 4);
            allowAll.Click += delegate { SetSelectedUserFeatures(true); };
            tools.Controls.Add(allowAll);

            Button denyAll = new Button();
            denyAll.Text = "全部关闭";
            denyAll.Width = 90;
            denyAll.Height = 30;
            denyAll.Margin = new Padding(4, 6, 4, 4);
            denyAll.Click += delegate { SetSelectedUserFeatures(false); };
            tools.Controls.Add(denyAll);

            runtimeFeatureUserLabel = new Label();
            runtimeFeatureUserLabel.Text = "输入 QQ 号后，勾选这个人可以使用的功能。";
            runtimeFeatureUserLabel.AutoSize = true;
            runtimeFeatureUserLabel.Margin = new Padding(16, 11, 4, 4);
            tools.Controls.Add(runtimeFeatureUserLabel);

            FlowLayoutPanel featureFlow = new FlowLayoutPanel();
            featureFlow.Dock = DockStyle.Fill;
            featureFlow.AutoScroll = true;
            featureFlow.WrapContents = true;
            layout.Controls.Add(featureFlow, 0, 1);

            foreach (KeyValuePair<string, string> item in featureLabels)
            {
                CheckBox check = new CheckBox();
                check.Text = item.Value;
                check.Tag = item.Key;
                check.Width = 170;
                check.Height = 34;
                check.Appearance = Appearance.Button;
                check.TextAlign = ContentAlignment.MiddleCenter;
                check.Margin = new Padding(4);
                check.Enabled = false;
                check.CheckedChanged += delegate(object sender, EventArgs args)
                {
                    if (updatingUi || selectedFeatureUser.Length == 0) return;
                    CheckBox box = (CheckBox)sender;
                    EnsureUserFeatureEntry(selectedFeatureUser);
                    config.user_features[selectedFeatureUser][(string)box.Tag] = box.Checked;
                    SaveConfig();
                    RefreshUserFeatureUi();
                    SetMessage("单人功能权限已保存。");
                };
                runtimeUserFeatureChecks[item.Key] = check;
                featureFlow.Controls.Add(check);
            }
        }

        private void BuildQuickAccessEditor(GroupBox parent)
        {
            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.ColumnCount = 2;
            layout.RowCount = 2;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            parent.Controls.Add(layout);

            FlowLayoutPanel tools = new FlowLayoutPanel();
            tools.Dock = DockStyle.Fill;
            tools.FlowDirection = FlowDirection.LeftToRight;
            tools.WrapContents = false;
            layout.SetColumnSpan(tools, 2);
            layout.Controls.Add(tools, 0, 0);

            quickAccessAllRadio = new RadioButton();
            quickAccessAllRadio.Text = "允许所有人";
            quickAccessAllRadio.Width = 105;
            quickAccessAllRadio.Height = 32;
            quickAccessAllRadio.CheckedChanged += delegate { if (!updatingUi && quickAccessAllRadio.Checked) { config.access_mode = "all"; SaveAndRefresh("已切换为允许所有人。"); } };
            tools.Controls.Add(quickAccessAllRadio);

            quickAccessAllowlistRadio = new RadioButton();
            quickAccessAllowlistRadio.Text = "只允许名单";
            quickAccessAllowlistRadio.Width = 115;
            quickAccessAllowlistRadio.Height = 32;
            quickAccessAllowlistRadio.CheckedChanged += delegate { if (!updatingUi && quickAccessAllowlistRadio.Checked) { config.access_mode = "allowlist"; SaveAndRefresh("已切换为白名单模式。"); } };
            tools.Controls.Add(quickAccessAllowlistRadio);

            quickUserInput = new TextBox();
            quickUserInput.Width = 170;
            quickUserInput.Height = 30;
            quickUserInput.Margin = new Padding(20, 7, 6, 4);
            quickUserInput.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Enter)
                {
                    AddListItem(config.allowed_users, quickUserInput);
                    e.SuppressKeyPress = true;
                }
            };
            tools.Controls.Add(quickUserInput);

            Button addAllowed = new Button();
            addAllowed.Text = "加入允许QQ";
            addAllowed.Width = 100;
            addAllowed.Height = 32;
            addAllowed.Click += delegate { AddListItem(config.allowed_users, quickUserInput); };
            tools.Controls.Add(addAllowed);

            Button addBlocked = new Button();
            addBlocked.Text = "加入禁止QQ";
            addBlocked.Width = 100;
            addBlocked.Height = 32;
            addBlocked.Click += delegate { AddListItem(config.blocked_users, quickUserInput); };
            tools.Controls.Add(addBlocked);

            quickAllowedUsersList = MakeQuickList("允许的 QQ", layout, 0);
            quickBlockedUsersList = MakeQuickList("禁止的 QQ", layout, 1);
        }

        private ListBox MakeQuickList(string title, TableLayoutPanel parent, int column)
        {
            GroupBox box = new GroupBox();
            box.Text = title;
            box.Dock = DockStyle.Fill;
            box.Padding = new Padding(10);
            parent.Controls.Add(box, column, 1);

            TableLayoutPanel inner = new TableLayoutPanel();
            inner.Dock = DockStyle.Fill;
            inner.RowCount = 2;
            inner.ColumnCount = 1;
            inner.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            inner.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            box.Controls.Add(inner);

            ListBox list = new ListBox();
            list.Dock = DockStyle.Fill;
            inner.Controls.Add(list, 0, 0);

            Button remove = new Button();
            remove.Text = "删除选中";
            remove.Dock = DockStyle.Fill;
            remove.Click += delegate { RemoveSelectedListItem(list); };
            inner.Controls.Add(remove, 0, 1);
            return list;
        }

        private Label MakeStatusLabel(string text)
        {
            Label label = new Label();
            label.Text = text;
            label.Dock = DockStyle.Fill;
            label.Height = 36;
            label.TextAlign = ContentAlignment.MiddleLeft;
            return label;
        }

        private void BuildAccessPage(TabPage page)
        {
            page.BackColor = BackColor;

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.Padding = new Padding(18);
            layout.ColumnCount = 2;
            layout.RowCount = 3;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 64));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 50));
            page.Controls.Add(layout);

            GroupBox modeBox = new GroupBox();
            modeBox.Text = "访问模式";
            modeBox.Dock = DockStyle.Fill;
            layout.SetColumnSpan(modeBox, 2);
            layout.Controls.Add(modeBox, 0, 0);

            accessAllRadio = new RadioButton();
            accessAllRadio.Text = "允许所有人";
            accessAllRadio.Location = new Point(18, 25);
            accessAllRadio.AutoSize = true;
            accessAllRadio.CheckedChanged += delegate { if (!updatingUi && accessAllRadio.Checked) { config.access_mode = "all"; SaveAndRefresh("已切换为允许所有人。"); } };
            modeBox.Controls.Add(accessAllRadio);

            accessAllowlistRadio = new RadioButton();
            accessAllowlistRadio.Text = "只允许名单";
            accessAllowlistRadio.Location = new Point(150, 25);
            accessAllowlistRadio.AutoSize = true;
            accessAllowlistRadio.CheckedChanged += delegate { if (!updatingUi && accessAllowlistRadio.Checked) { config.access_mode = "allowlist"; SaveAndRefresh("已切换为白名单模式。"); } };
            modeBox.Controls.Add(accessAllowlistRadio);

            allowedUsersList = AddListEditor(layout, "允许的 QQ", 0, 1, out allowedUsersInput, delegate { AddListItem(config.allowed_users, allowedUsersInput); });
            blockedUsersList = AddListEditor(layout, "禁止的 QQ", 1, 1, out blockedUsersInput, delegate { AddListItem(config.blocked_users, blockedUsersInput); });
            allowedGroupsList = AddListEditor(layout, "允许的群", 0, 2, out allowedGroupsInput, delegate { AddListItem(config.allowed_groups, allowedGroupsInput); });
            blockedGroupsList = AddListEditor(layout, "禁止的群", 1, 2, out blockedGroupsInput, delegate { AddListItem(config.blocked_groups, blockedGroupsInput); });
        }

        private ListBox AddListEditor(TableLayoutPanel parent, string title, int column, int row, out TextBox input, EventHandler addHandler)
        {
            GroupBox box = new GroupBox();
            box.Text = title;
            box.Dock = DockStyle.Fill;
            box.Padding = new Padding(12);
            parent.Controls.Add(box, column, row);

            TableLayoutPanel inner = new TableLayoutPanel();
            inner.Dock = DockStyle.Fill;
            inner.ColumnCount = 3;
            inner.RowCount = 2;
            inner.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            inner.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 82));
            inner.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 82));
            inner.RowStyles.Add(new RowStyle(SizeType.Absolute, 38));
            inner.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            box.Controls.Add(inner);

            input = new TextBox();
            input.Dock = DockStyle.Fill;
            inner.Controls.Add(input, 0, 0);

            Button add = new Button();
            add.Text = "添加";
            add.Dock = DockStyle.Fill;
            add.Click += addHandler;
            inner.Controls.Add(add, 1, 0);

            ListBox list = new ListBox();
            list.Dock = DockStyle.Fill;
            inner.SetColumnSpan(list, 3);
            inner.Controls.Add(list, 0, 1);

            Button remove = new Button();
            remove.Text = "删除选中";
            remove.Dock = DockStyle.Fill;
            remove.Click += delegate
            {
                if (list.SelectedItem == null) return;
                RemoveSelectedListItem(list);
            };
            inner.Controls.Add(remove, 2, 0);
            return list;
        }

        private void BuildUserFeaturePage(TabPage page)
        {
            page.BackColor = BackColor;

            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.Padding = new Padding(18);
            layout.ColumnCount = 2;
            layout.RowCount = 2;
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 280));
            layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 78));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.Controls.Add(layout);

            GroupBox inputBox = new GroupBox();
            inputBox.Text = "选择 QQ";
            inputBox.Dock = DockStyle.Fill;
            inputBox.Padding = new Padding(12);
            layout.SetColumnSpan(inputBox, 2);
            layout.Controls.Add(inputBox, 0, 0);

            FlowLayoutPanel inputFlow = new FlowLayoutPanel();
            inputFlow.Dock = DockStyle.Fill;
            inputFlow.FlowDirection = FlowDirection.LeftToRight;
            inputFlow.WrapContents = false;
            inputBox.Controls.Add(inputFlow);

            featureUserInput = new TextBox();
            featureUserInput.Width = 180;
            featureUserInput.Margin = new Padding(4, 12, 8, 4);
            featureUserInput.KeyDown += delegate(object sender, KeyEventArgs e)
            {
                if (e.KeyCode == Keys.Enter)
                {
                    SelectFeatureUser(featureUserInput.Text);
                    e.SuppressKeyPress = true;
                }
            };
            inputFlow.Controls.Add(featureUserInput);

            Button loadUser = new Button();
            loadUser.Text = "载入/新增";
            loadUser.Width = 96;
            loadUser.Height = 32;
            loadUser.Margin = new Padding(4, 10, 4, 4);
            loadUser.Click += delegate { SelectFeatureUser(featureUserInput.Text); };
            inputFlow.Controls.Add(loadUser);

            Button deleteUser = new Button();
            deleteUser.Text = "删除该QQ设置";
            deleteUser.Width = 120;
            deleteUser.Height = 32;
            deleteUser.Margin = new Padding(4, 10, 4, 4);
            deleteUser.Click += delegate { DeleteSelectedFeatureUser(); };
            inputFlow.Controls.Add(deleteUser);

            Button allowAll = new Button();
            allowAll.Text = "该QQ全部开启";
            allowAll.Width = 120;
            allowAll.Height = 32;
            allowAll.Margin = new Padding(4, 10, 4, 4);
            allowAll.Click += delegate { SetSelectedUserFeatures(true); };
            inputFlow.Controls.Add(allowAll);

            Button denyAll = new Button();
            denyAll.Text = "该QQ全部关闭";
            denyAll.Width = 120;
            denyAll.Height = 32;
            denyAll.Margin = new Padding(4, 10, 4, 4);
            denyAll.Click += delegate { SetSelectedUserFeatures(false); };
            inputFlow.Controls.Add(denyAll);

            GroupBox usersBox = new GroupBox();
            usersBox.Text = "已有单人设置";
            usersBox.Dock = DockStyle.Fill;
            usersBox.Padding = new Padding(12);
            layout.Controls.Add(usersBox, 0, 1);

            featureUsersList = new ListBox();
            featureUsersList.Dock = DockStyle.Fill;
            featureUsersList.SelectedIndexChanged += delegate
            {
                if (updatingUi || featureUsersList.SelectedItem == null) return;
                SelectFeatureUser(Convert.ToString(featureUsersList.SelectedItem));
            };
            usersBox.Controls.Add(featureUsersList);

            GroupBox featuresBox = new GroupBox();
            featuresBox.Text = "该 QQ 可使用的功能";
            featuresBox.Dock = DockStyle.Fill;
            featuresBox.Padding = new Padding(14);
            layout.Controls.Add(featuresBox, 1, 1);

            TableLayoutPanel rightLayout = new TableLayoutPanel();
            rightLayout.Dock = DockStyle.Fill;
            rightLayout.RowCount = 2;
            rightLayout.ColumnCount = 1;
            rightLayout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            rightLayout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            featuresBox.Controls.Add(rightLayout);

            featureUserLabel = new Label();
            featureUserLabel.Text = "未选择 QQ";
            featureUserLabel.Dock = DockStyle.Fill;
            featureUserLabel.TextAlign = ContentAlignment.MiddleLeft;
            rightLayout.Controls.Add(featureUserLabel, 0, 0);

            FlowLayoutPanel featureFlow = new FlowLayoutPanel();
            featureFlow.Dock = DockStyle.Fill;
            featureFlow.AutoScroll = true;
            featureFlow.WrapContents = true;
            rightLayout.Controls.Add(featureFlow, 0, 1);

            foreach (KeyValuePair<string, string> item in featureLabels)
            {
                CheckBox check = new CheckBox();
                check.Text = item.Value;
                check.Tag = item.Key;
                check.Width = 300;
                check.Height = 44;
                check.Appearance = Appearance.Button;
                check.TextAlign = ContentAlignment.MiddleCenter;
                check.Margin = new Padding(8);
                check.Enabled = false;
                check.CheckedChanged += delegate(object sender, EventArgs args)
                {
                    if (updatingUi || selectedFeatureUser.Length == 0) return;
                    CheckBox box = (CheckBox)sender;
                    EnsureUserFeatureEntry(selectedFeatureUser);
                    config.user_features[selectedFeatureUser][(string)box.Tag] = box.Checked;
                    SaveConfig();
                    RefreshUserFeatureUi();
                    SetMessage("单人功能权限已保存。");
                };
                userFeatureChecks[item.Key] = check;
                featureFlow.Controls.Add(check);
            }
        }

        private void BuildFeaturePage(TabPage page)
        {
            page.BackColor = BackColor;
            Panel panel = new Panel();
            panel.Dock = DockStyle.Fill;
            panel.Padding = new Padding(22);
            page.Controls.Add(panel);

            FlowLayoutPanel flow = new FlowLayoutPanel();
            flow.Dock = DockStyle.Fill;
            flow.AutoScroll = true;
            flow.WrapContents = true;
            panel.Controls.Add(flow);

            foreach (KeyValuePair<string, string> item in featureLabels)
            {
                CheckBox check = new CheckBox();
                check.Text = item.Value;
                check.Tag = item.Key;
                check.Width = 300;
                check.Height = 44;
                check.Appearance = Appearance.Button;
                check.TextAlign = ContentAlignment.MiddleCenter;
                check.Margin = new Padding(8);
                check.CheckedChanged += delegate(object sender, EventArgs args)
                {
                    if (updatingUi) return;
                    CheckBox box = (CheckBox)sender;
                    config.features[(string)box.Tag] = box.Checked;
                    SaveConfig();
                    SetMessage("功能开关已保存。");
                };
                featureChecks[item.Key] = check;
                flow.Controls.Add(check);
            }

            Button enableAll = MakeButton("全部开启", delegate
            {
                foreach (string key in featureLabels.Keys)
                {
                    config.features[key] = true;
                }
                SaveAndRefresh("所有功能已开启。");
            });
            enableAll.Width = 300;
            flow.Controls.Add(enableAll);
        }

        private void BuildLogPage(TabPage page)
        {
            page.BackColor = BackColor;
            TableLayoutPanel layout = new TableLayoutPanel();
            layout.Dock = DockStyle.Fill;
            layout.Padding = new Padding(18);
            layout.RowCount = 2;
            layout.ColumnCount = 1;
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 44));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            page.Controls.Add(layout);

            FlowLayoutPanel top = new FlowLayoutPanel();
            top.Dock = DockStyle.Fill;
            top.FlowDirection = FlowDirection.LeftToRight;
            layout.Controls.Add(top, 0, 0);

            logTargetCombo = new ComboBox();
            logTargetCombo.DropDownStyle = ComboBoxStyle.DropDownList;
            logTargetCombo.Width = 180;
            logTargetCombo.Items.AddRange(new object[] { "nonebot", "napcat", "setup", "dependencies", "manager" });
            logTargetCombo.SelectedIndex = 0;
            logTargetCombo.SelectedIndexChanged += delegate { LoadLog(); };
            top.Controls.Add(logTargetCombo);

            Button refresh = MakeButton("刷新日志", delegate { LoadLog(); });
            refresh.Width = 110;
            top.Controls.Add(refresh);

            Button openLogs = MakeButton("打开日志文件夹", delegate { Process.Start(logDir); });
            openLogs.Width = 140;
            top.Controls.Add(openLogs);

            logBox = new TextBox();
            logBox.Dock = DockStyle.Fill;
            logBox.Multiline = true;
            logBox.ScrollBars = ScrollBars.Both;
            logBox.ReadOnly = true;
            logBox.Font = new Font("Consolas", 9F);
            logBox.BackColor = Color.FromArgb(17, 24, 29);
            logBox.ForeColor = Color.FromArgb(220, 232, 235);
            layout.Controls.Add(logBox, 0, 1);
        }

        private void AddListItem(List<string> list, TextBox input)
        {
            string value = (input.Text ?? "").Trim();
            if (value.Length == 0) return;
            if (!list.Contains(value))
            {
                list.Add(value);
            }
            input.Text = "";
            SaveAndRefresh("名单已保存。");
        }

        private void RemoveSelectedListItem(ListBox list)
        {
            string value = Convert.ToString(list.SelectedItem);
            if (list == allowedUsersList) config.allowed_users.Remove(value);
            if (list == blockedUsersList) config.blocked_users.Remove(value);
            if (list == allowedGroupsList) config.allowed_groups.Remove(value);
            if (list == blockedGroupsList) config.blocked_groups.Remove(value);
            if (list == quickAllowedUsersList) config.allowed_users.Remove(value);
            if (list == quickBlockedUsersList) config.blocked_users.Remove(value);
            SaveAndRefresh("名单已保存。");
        }

        private void SelectFeatureUser(string rawUserId)
        {
            string userId = (rawUserId ?? "").Trim();
            if (userId.Length == 0)
            {
                SetMessage("请输入 QQ 号。");
                return;
            }

            EnsureUserFeatureEntry(userId);
            selectedFeatureUser = userId;
            if (featureUserInput != null) featureUserInput.Text = userId;
            if (runtimeFeatureUserInput != null) runtimeFeatureUserInput.Text = userId;
            SaveConfig();
            RefreshUserFeatureUi();
            SetMessage("正在管理 QQ " + userId + " 的单独功能权限。");
        }

        private void EnsureUserFeatureEntry(string userId)
        {
            if (config.user_features == null)
            {
                config.user_features = new Dictionary<string, Dictionary<string, bool>>();
            }
            if (!config.user_features.ContainsKey(userId))
            {
                config.user_features[userId] = new Dictionary<string, bool>();
            }
            foreach (string key in featureLabels.Keys)
            {
                if (!config.user_features[userId].ContainsKey(key))
                {
                    config.user_features[userId][key] = true;
                }
            }
        }

        private void DeleteSelectedFeatureUser()
        {
            if (selectedFeatureUser.Length == 0)
            {
                SetMessage("还没有选择 QQ。");
                return;
            }
            if (config.user_features != null)
            {
                config.user_features.Remove(selectedFeatureUser);
            }
            selectedFeatureUser = "";
            if (featureUserInput != null) featureUserInput.Text = "";
            if (runtimeFeatureUserInput != null) runtimeFeatureUserInput.Text = "";
            SaveConfig();
            RefreshUserFeatureUi();
            SetMessage("已删除该 QQ 的单人功能设置。");
        }

        private void SetSelectedUserFeatures(bool enabled)
        {
            if (selectedFeatureUser.Length == 0)
            {
                SetMessage("请先输入并载入 QQ 号。");
                return;
            }
            EnsureUserFeatureEntry(selectedFeatureUser);
            foreach (string key in featureLabels.Keys)
            {
                config.user_features[selectedFeatureUser][key] = enabled;
            }
            SaveConfig();
            RefreshUserFeatureUi();
            SetMessage(enabled ? "该 QQ 的功能已全部开启。" : "该 QQ 的功能已全部关闭。");
        }

        private void RefreshUserFeatureUi()
        {
            if (featureUsersList == null || featureUserLabel == null)
            {
                return;
            }

            updatingUi = true;
            try
            {
                featureUsersList.Items.Clear();
                if (config.user_features != null)
                {
                    foreach (string userId in config.user_features.Keys.OrderBy(x => x))
                    {
                        featureUsersList.Items.Add(userId);
                    }
                }

                if (selectedFeatureUser.Length > 0 && featureUsersList.Items.Contains(selectedFeatureUser))
                {
                    featureUsersList.SelectedItem = selectedFeatureUser;
                }

                featureUserLabel.Text = selectedFeatureUser.Length == 0
                    ? "未选择 QQ"
                    : "正在设置 QQ：" + selectedFeatureUser + "。取消勾选即可禁止该 QQ 使用对应功能。";
                if (runtimeFeatureUserLabel != null)
                {
                    runtimeFeatureUserLabel.Text = selectedFeatureUser.Length == 0
                        ? "输入 QQ 号后，勾选这个人可以使用的功能。"
                        : "正在设置 QQ：" + selectedFeatureUser;
                }

                foreach (KeyValuePair<string, CheckBox> item in userFeatureChecks)
                {
                    item.Value.Enabled = selectedFeatureUser.Length > 0;
                    bool value = true;
                    if (selectedFeatureUser.Length > 0
                        && config.user_features != null
                        && config.user_features.ContainsKey(selectedFeatureUser)
                        && config.user_features[selectedFeatureUser].ContainsKey(item.Key))
                    {
                        value = config.user_features[selectedFeatureUser][item.Key];
                    }
                    item.Value.Checked = value;
                }

                foreach (KeyValuePair<string, CheckBox> item in runtimeUserFeatureChecks)
                {
                    item.Value.Enabled = selectedFeatureUser.Length > 0;
                    bool value = true;
                    if (selectedFeatureUser.Length > 0
                        && config.user_features != null
                        && config.user_features.ContainsKey(selectedFeatureUser)
                        && config.user_features[selectedFeatureUser].ContainsKey(item.Key))
                    {
                        value = config.user_features[selectedFeatureUser][item.Key];
                    }
                    item.Value.Checked = value;
                }
            }
            finally
            {
                updatingUi = false;
            }
        }

        private void SaveAndRefresh(string message)
        {
            SaveConfig();
            RefreshConfigUi();
            RefreshUserFeatureUi();
            SetMessage(message);
        }

        private void RefreshConfigUi()
        {
            updatingUi = true;
            try
            {
                accessAllRadio.Checked = config.access_mode != "allowlist";
                accessAllowlistRadio.Checked = config.access_mode == "allowlist";
                if (quickAccessAllRadio != null) quickAccessAllRadio.Checked = config.access_mode != "allowlist";
                if (quickAccessAllowlistRadio != null) quickAccessAllowlistRadio.Checked = config.access_mode == "allowlist";
                FillList(allowedUsersList, config.allowed_users);
                FillList(blockedUsersList, config.blocked_users);
                FillList(allowedGroupsList, config.allowed_groups);
                FillList(blockedGroupsList, config.blocked_groups);
                if (quickAllowedUsersList != null) FillList(quickAllowedUsersList, config.allowed_users);
                if (quickBlockedUsersList != null) FillList(quickBlockedUsersList, config.blocked_users);

                foreach (KeyValuePair<string, CheckBox> item in featureChecks)
                {
                    bool value = config.features.ContainsKey(item.Key) && config.features[item.Key];
                    if (item.Value.Checked != value)
                    {
                        item.Value.Checked = value;
                    }
                }
            }
            finally
            {
                updatingUi = false;
            }
        }

        private void FillList(ListBox box, List<string> values)
        {
            box.Items.Clear();
            foreach (string value in values)
            {
                box.Items.Add(value);
            }
        }

        private void RefreshAll()
        {
            if (!updatingUi)
            {
                ReloadConfigIfChanged();
            }
            RefreshStatus();
            RefreshConfigUi();
            RefreshUserFeatureUi();
            LoadLog();
        }

        private void RefreshStatus()
        {
            bool nonebotRunning = IsRunning("nonebot");
            bool napcatRunning = IsRunning("napcat");
            bool portOpen = IsPortOpen(8081);
            int externalNonebotPid = nonebotRunning ? 0 : GetListeningPid(8081);
            PythonCommand python = FindPython();

            Color runningColor = Color.FromArgb(13, 138, 95);
            Color stoppedColor = Color.FromArgb(138, 149, 158);
            Color warnColor = Color.FromArgb(198, 118, 15);
            Color errorColor = Color.FromArgb(192, 57, 43);

            nonebotStatus.Text = nonebotRunning
                ? ProcessStatusText("NoneBot", "nonebot")
                : (externalNonebotPid > 0
                    ? "NoneBot：运行中，PID " + externalNonebotPid + "（外部启动）"
                    : (portOpen ? "NoneBot：8081 端口已打开，可能由外部启动" : "NoneBot：未启动"));
            nonebotStatus.ForeColor = nonebotRunning || externalNonebotPid > 0 ? runningColor : (portOpen ? warnColor : stoppedColor);

            bool napcatExternal = IsNapCatRunning();
            napcatStatus.Text = (napcatRunning || napcatExternal) ? ProcessStatusText("NapCat", "napcat") : "NapCat：未由本程序启动";
            napcatStatus.ForeColor = (napcatRunning || napcatExternal) ? runningColor : stoppedColor;

            portStatus.Text = portOpen ? "OneBot 端口：8081 已监听" : "OneBot 端口：8081 未监听";
            portStatus.ForeColor = portOpen ? runningColor : stoppedColor;

            pythonStatus.Text = python == null ? "Python：不可用，请安装 Python 3.10+ 或修复 .venv" : "Python：" + python.DisplayName;
            pythonStatus.ForeColor = python == null ? errorColor : runningColor;
        }

        private string ProcessStatusText(string label, string key)
        {
            ManagedProcess managed = processes.ContainsKey(key) ? processes[key] : null;
            if (managed == null || managed.Process == null)
            {
                return label + "：运行中";
            }
            return string.Format("{0}：运行中，PID {1}", label, managed.Process.Id);
        }

        private bool IsRunning(string key)
        {
            if (!processes.ContainsKey(key) || processes[key].Process == null)
            {
                return false;
            }
            try
            {
                return !processes[key].Process.HasExited;
            }
            catch
            {
                return false;
            }
        }

        private bool IsNapCatRunning()
        {
            try
            {
                Process[] procs = Process.GetProcessesByName("NapCatWinBootMain");
                bool any = procs.Length > 0;
                foreach (Process p in procs) { p.Dispose(); }
                return any;
            }
            catch
            {
                return false;
            }
        }

        private int[] FindNapCatPids()
        {
            List<int> pids = new List<int>();
            try
            {
                foreach (Process p in Process.GetProcessesByName("NapCatWinBootMain"))
                {
                    pids.Add(p.Id);
                    p.Dispose();
                }
            }
            catch { }
            return pids.ToArray();
        }

        private bool IsPortOpen(int port)
        {
            try
            {
                using (TcpClient client = new TcpClient())
                {
                    IAsyncResult result = client.BeginConnect("127.0.0.1", port, null, null);
                    if (!result.AsyncWaitHandle.WaitOne(250))
                    {
                        return false;
                    }
                    client.EndConnect(result);
                    return true;
                }
            }
            catch
            {
                return false;
            }
        }

        private int GetListeningPid(int port)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = "netstat";
                psi.Arguments = "-ano -p tcp";
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.CreateNoWindow = true;

                using (Process process = Process.Start(psi))
                {
                    string output = process.StandardOutput.ReadToEnd();
                    process.WaitForExit(3000);
                    string needle = ":" + port.ToString();
                    foreach (string rawLine in output.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                    {
                        string line = rawLine.Trim();
                        if (!line.Contains(needle) || !line.Contains("LISTENING"))
                        {
                            continue;
                        }

                        string[] parts = line.Split(new[] { ' ' }, StringSplitOptions.RemoveEmptyEntries);
                        if (parts.Length >= 5)
                        {
                            int pid;
                            if (int.TryParse(parts[parts.Length - 1], out pid))
                            {
                                return pid;
                            }
                        }
                    }
                }
            }
            catch { }
            return 0;
        }

        private void StartAll()
        {
            StartNoneBot();
            DateTime deadline = DateTime.Now.AddSeconds(8);
            while (DateTime.Now < deadline && !IsPortOpen(8081))
            {
                Application.DoEvents();
                System.Threading.Thread.Sleep(250);
            }
            StartNapCat();
        }

        private void StopAll()
        {
            StopProcess("napcat");
            StopProcess("nonebot");
        }

        private void StartNoneBot()
        {
            if (IsRunning("nonebot"))
            {
                SetMessage("NoneBot 已在运行。");
                return;
            }
            if (IsPortOpen(8081))
            {
                SetMessage("NoneBot 已在 8081 端口运行；如需重启，请先停止 NoneBot。");
                return;
            }

            PythonCommand python = FindPython();
            if (python == null)
            {
                SetMessage("Python 不可用，无法启动 NoneBot。");
                WriteLog("nonebot", "Python 不可用，无法启动 NoneBot。");
                return;
            }

            string args = JoinArgs(python.PrefixArgs, Quote(Path.Combine(root, "bot.py")));
            StartManaged("nonebot", python.FileName, args, root);
        }

        private void UpdateRestartNoneBot()
        {
            DialogResult result = MessageBox.Show(
                "将停止并重新启动 NoneBot，加载最新代码。\n\n确定继续？",
                "更新重启 NoneBot",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Question
            );
            if (result != DialogResult.Yes)
            {
                return;
            }

            SetMessage("更新重启：正在停止 NoneBot...");
            WriteLog("nonebot", "更新重启：开始停止。");
            StopProcess("nonebot");

            if (IsPortOpen(8081))
            {
                int externalPid = GetListeningPid(8081);
                if (externalPid > 0)
                {
                    KillProcessTree(externalPid);
                    WriteLog("nonebot", "更新重启：停止占用 8081 的外部进程 PID " + externalPid);
                }
            }

            for (int i = 0; i < 30 && IsPortOpen(8081); i++)
            {
                Application.DoEvents();
                System.Threading.Thread.Sleep(500);
            }
            if (IsPortOpen(8081))
            {
                SetMessage("更新重启失败：8081 端口仍被占用，请手动检查。");
                WriteLog("nonebot", "更新重启失败：8081 端口仍被占用。");
                return;
            }

            SetMessage("更新重启：正在启动 NoneBot...");
            WriteLog("nonebot", "更新重启：开始启动。");
            StartNoneBot();
        }

        private void StartNapCat()
        {
            if (IsRunning("napcat") || IsNapCatRunning())
            {
                SetMessage("NapCat 已在运行。");
                return;
            }

            string napcatRoot = Path.Combine(root, "NapCat.Shell");
            string launcher = Directory.Exists(napcatRoot)
                ? Directory.GetFiles(napcatRoot, "launcher.bat", SearchOption.AllDirectories).FirstOrDefault()
                : null;
            if (launcher == null)
            {
                SetMessage("没有找到 NapCat.Shell\\launcher.bat，请先安装/修复 NapCat。");
                return;
            }

            string account = ReadEnv("QQ_BOT_ACCOUNT");
            if (account.Length == 0) account = "100000000";
            string args = "/c call " + Quote(launcher) + " " + account;
            StartManaged("napcat", "cmd.exe", args, Path.GetDirectoryName(launcher));
        }

        private void SetupNapCat()
        {
            string script = Path.Combine(root, "setup_napcat_shell.ps1");
            if (!File.Exists(script))
            {
                SetMessage("找不到 setup_napcat_shell.ps1。");
                return;
            }
            string args = "-NoProfile -ExecutionPolicy Bypass -File " + Quote(script);
            StartManaged("setup", "powershell.exe", args, root);
        }

        private void InstallDependencies()
        {
            PythonCommand python = FindPython();
            if (python == null)
            {
                SetMessage("Python 不可用，无法安装依赖。");
                return;
            }
            string requirements = Path.Combine(root, "requirements.txt");
            string args = JoinArgs(python.PrefixArgs, "-m pip install -r " + Quote(requirements));
            StartManaged("dependencies", python.FileName, args, root);
        }

        private void CleanCacheFiles()
        {
            DialogResult result = MessageBox.Show(
                "将清理可重新生成的缓存文件：\n\n"
                + "1. plugins\\download（机器人发送用临时图片/压缩包缓存）\n"
                + "2. plugins\\__pycache__ 和插件 .pyc 文件\n"
                + "3. qrcode.png 旧二维码文件\n\n"
                + "不会删除 downloads 里的手动下载漫画，也不会删除 QQ/NapCat 登录数据。\n\n"
                + "确定继续？",
                "清理缓存文件",
                MessageBoxButtons.YesNo,
                MessageBoxIcon.Warning
            );
            if (result != DialogResult.Yes)
            {
                return;
            }

            int deletedFiles = 0;
            int deletedDirs = 0;
            long deletedBytes = 0;

            DeleteDirectoryCache(Path.Combine(root, "plugins", "download"), ref deletedFiles, ref deletedDirs, ref deletedBytes);
            DeleteDirectoryCache(Path.Combine(root, "plugins", "__pycache__"), ref deletedFiles, ref deletedDirs, ref deletedBytes);

            string pluginsRoot = Path.Combine(root, "plugins");
            if (Directory.Exists(pluginsRoot))
            {
                foreach (string file in Directory.GetFiles(pluginsRoot, "*.pyc", SearchOption.AllDirectories))
                {
                    DeleteFileCache(file, ref deletedFiles, ref deletedBytes);
                }
            }

            DeleteFileCache(Path.Combine(root, "qrcode.png"), ref deletedFiles, ref deletedBytes);

            string message = string.Format(
                "缓存清理完成：删除 {0} 个文件、{1} 个文件夹，约 {2}。",
                deletedFiles,
                deletedDirs,
                FormatBytes(deletedBytes)
            );
            SetMessage(message);
            WriteLog("manager", message);
        }

        private void DeleteDirectoryCache(string path, ref int deletedFiles, ref int deletedDirs, ref long deletedBytes)
        {
            try
            {
                if (!Directory.Exists(path) || !IsSafeProjectPath(path))
                {
                    return;
                }

                foreach (string file in Directory.GetFiles(path, "*", SearchOption.AllDirectories))
                {
                    try
                    {
                        FileInfo info = new FileInfo(file);
                        deletedBytes += info.Exists ? info.Length : 0;
                        deletedFiles++;
                    }
                    catch { }
                }

                Directory.Delete(path, true);
                deletedDirs++;
                WriteLog("manager", "已清理缓存目录：" + path);
            }
            catch (Exception ex)
            {
                WriteLog("manager", "清理缓存目录失败：" + path + "，" + ex.Message);
                SetMessage("部分缓存清理失败，请先停止正在发送图片/文件的任务后重试。");
            }
        }

        private void DeleteFileCache(string path, ref int deletedFiles, ref long deletedBytes)
        {
            try
            {
                if (!File.Exists(path) || !IsSafeProjectPath(path))
                {
                    return;
                }

                FileInfo info = new FileInfo(path);
                deletedBytes += info.Exists ? info.Length : 0;
                File.Delete(path);
                deletedFiles++;
                WriteLog("manager", "已清理缓存文件：" + path);
            }
            catch (Exception ex)
            {
                WriteLog("manager", "清理缓存文件失败：" + path + "，" + ex.Message);
            }
        }

        private bool IsSafeProjectPath(string path)
        {
            try
            {
                string rootFull = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
                    + Path.DirectorySeparatorChar;
                string targetFull = Path.GetFullPath(path);
                return targetFull.StartsWith(rootFull, StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                return false;
            }
        }

        private string FormatBytes(long bytes)
        {
            if (bytes >= 1024L * 1024L * 1024L)
            {
                return (bytes / 1024d / 1024d / 1024d).ToString("0.##") + " GB";
            }
            if (bytes >= 1024L * 1024L)
            {
                return (bytes / 1024d / 1024d).ToString("0.##") + " MB";
            }
            if (bytes >= 1024L)
            {
                return (bytes / 1024d).ToString("0.##") + " KB";
            }
            return bytes + " B";
        }

        private void StartManaged(string key, string fileName, string args, string workingDirectory)
        {
            try
            {
                ManagedProcess existing = processes.ContainsKey(key) ? processes[key] : null;
                if (existing != null && existing.Process != null && !existing.Process.HasExited)
                {
                    SetMessage(key + " 已在运行。");
                    return;
                }

                string logFile = Path.Combine(logDir, key + ".log");
                WriteLog(key, "Starting: " + fileName + " " + args);

                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = fileName;
                psi.Arguments = args;
                psi.WorkingDirectory = workingDirectory;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.CreateNoWindow = true;
                psi.StandardOutputEncoding = Encoding.UTF8;
                psi.StandardErrorEncoding = Encoding.UTF8;
                psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";

                Process process = new Process();
                process.StartInfo = psi;
                process.EnableRaisingEvents = true;
                process.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) WriteLog(key, e.Data); };
                process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e) { if (e.Data != null) WriteLog(key, e.Data); };
                process.Exited += delegate { WriteLog(key, "Process exited: " + process.ExitCode); BeginInvoke((Action)RefreshStatus); };
                process.Start();
                process.BeginOutputReadLine();
                process.BeginErrorReadLine();

                ManagedProcess managed = new ManagedProcess();
                managed.Name = key;
                managed.Process = process;
                managed.LogFile = logFile;
                managed.StartedAt = DateTime.Now;
                processes[key] = managed;
                SetMessage(key + " 已启动，PID " + process.Id);
                RefreshStatus();
            }
            catch (Exception ex)
            {
                WriteLog(key, "启动失败：" + ex.Message);
                SetMessage("启动失败：" + ex.Message);
            }
        }

        private void StopProcess(string key)
        {
            try
            {
                if (!IsRunning(key))
                {
                    if (key == "napcat")
                    {
                        int[] napcatPids = FindNapCatPids();
                        if (napcatPids.Length > 0)
                        {
                            foreach (int napcatPid in napcatPids)
                            {
                                KillProcessTree(napcatPid);
                            }
                            SetMessage("napcat 已停止（外部进程）。");
                            WriteLog(key, "Stopped external NapCatWinBootMain PIDs " + string.Join(",", napcatPids));
                            RefreshStatus();
                            return;
                        }
                    }
                    if (key == "nonebot")
                    {
                        int externalPid = GetListeningPid(8081);
                        if (externalPid > 0)
                        {
                            KillProcessTree(externalPid);
                            SetMessage("nonebot 已停止（外部进程 PID " + externalPid + "）。");
                            WriteLog(key, "Stopped external PID " + externalPid);
                            RefreshStatus();
                            return;
                        }
                    }
                    SetMessage(key + " 未由本程序启动。");
                    return;
                }
                int pid = processes[key].Process.Id;
                KillProcessTree(pid);
                SetMessage(key + " 已停止。");
                WriteLog(key, "Stopped PID " + pid);
                RefreshStatus();
            }
            catch (Exception ex)
            {
                SetMessage("停止失败：" + ex.Message);
            }
        }

        private void KillProcessTree(int pid)
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = "taskkill";
            psi.Arguments = "/PID " + pid + " /T /F";
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi).WaitForExit();
        }

        private PythonCommand FindPython()
        {
            List<PythonCommand> candidates = new List<PythonCommand>();
            string venv = Path.Combine(root, ".venv", "Scripts", "python.exe");
            if (File.Exists(venv))
            {
                candidates.Add(new PythonCommand { FileName = venv, PrefixArgs = "", DisplayName = venv });
            }
            candidates.Add(new PythonCommand { FileName = "python", PrefixArgs = "", DisplayName = "python" });
            candidates.Add(new PythonCommand { FileName = "py", PrefixArgs = "-3", DisplayName = "py -3" });

            foreach (PythonCommand candidate in candidates)
            {
                if (TestCommand(candidate.FileName, JoinArgs(candidate.PrefixArgs, "--version")))
                {
                    return candidate;
                }
            }
            return null;
        }

        private bool TestCommand(string fileName, string args)
        {
            try
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = fileName;
                psi.Arguments = args;
                psi.WorkingDirectory = root;
                psi.UseShellExecute = false;
                psi.RedirectStandardOutput = true;
                psi.RedirectStandardError = true;
                psi.CreateNoWindow = true;
                using (Process process = Process.Start(psi))
                {
                    if (!process.WaitForExit(5000))
                    {
                        try { process.Kill(); } catch { }
                        return false;
                    }
                    return process.ExitCode == 0;
                }
            }
            catch
            {
                return false;
            }
        }

        private string ReadEnv(string key)
        {
            try
            {
                if (!File.Exists(envFile)) return "";
                foreach (string line in File.ReadAllLines(envFile, Encoding.UTF8))
                {
                    string trimmed = line.Trim();
                    if (trimmed.StartsWith("#") || trimmed.Length == 0 || !trimmed.Contains("=")) continue;
                    int index = trimmed.IndexOf('=');
                    string name = trimmed.Substring(0, index).Trim();
                    if (name == key)
                    {
                        return trimmed.Substring(index + 1).Trim();
                    }
                }
            }
            catch { }
            return "";
        }

        private string Quote(string value)
        {
            return "\"" + value.Replace("\"", "\\\"") + "\"";
        }

        private string JoinArgs(string first, string second)
        {
            first = (first ?? "").Trim();
            second = (second ?? "").Trim();
            if (first.Length == 0) return second;
            if (second.Length == 0) return first;
            return first + " " + second;
        }

        private void WriteLog(string key, string text)
        {
            try
            {
                Directory.CreateDirectory(logDir);
                string path = Path.Combine(logDir, key + ".log");
                string line = string.Format("[{0:yyyy-MM-dd HH:mm:ss}] {1}\r\n", DateTime.Now, text);
                File.AppendAllText(path, line, Encoding.UTF8);
            }
            catch { }
        }

        private void LoadLog()
        {
            if (logTargetCombo == null || logBox == null) return;
            string key = Convert.ToString(logTargetCombo.SelectedItem ?? "nonebot");
            string path = Path.Combine(logDir, key + ".log");
            try
            {
                if (!File.Exists(path))
                {
                    logBox.Text = "暂无日志";
                    return;
                }
                string text = ReadSharedText(path);
                if (text.Length > 30000)
                {
                    text = text.Substring(text.Length - 30000);
                }
                if (logBox.Text != text)
                {
                    logBox.Text = text;
                    logBox.SelectionStart = logBox.TextLength;
                    logBox.ScrollToCaret();
                }
            }
            catch (Exception ex)
            {
                logBox.Text = "读取日志失败：" + ex.Message;
            }
        }

        private string ReadSharedText(string path)
        {
            using (FileStream stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete))
            using (StreamReader reader = new StreamReader(stream, Encoding.UTF8, true))
            {
                return reader.ReadToEnd();
            }
        }

        private void SetMessage(string message)
        {
            messageLabel.Text = message;
            WriteLog("manager", message);
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            if (!IsAdministrator())
            {
                ProcessStartInfo psi = new ProcessStartInfo();
                psi.FileName = Application.ExecutablePath;
                psi.UseShellExecute = true;
                psi.Verb = "runas";
                try
                {
                    Process.Start(psi);
                }
                catch
                {
                    // User canceled the UAC prompt; exit quietly.
                }
                return;
            }

            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            Application.Run(new MainForm());
        }

        private static bool IsAdministrator()
        {
            try
            {
                using (WindowsIdentity identity = WindowsIdentity.GetCurrent())
                {
                    WindowsPrincipal principal = new WindowsPrincipal(identity);
                    return principal.IsInRole(WindowsBuiltInRole.Administrator);
                }
            }
            catch
            {
                return false;
            }
        }
    }
}
