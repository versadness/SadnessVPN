using System;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace SadnessVPN {
    // Attached on the WinForms thread. No Python callbacks in the window procedure.
    public sealed class WindowChrome : NativeWindow {
        private readonly Form form;
        private Rectangle normalBounds;
        private int lastSizeState;
        [StructLayout(LayoutKind.Sequential)] private struct Rect { public int Left, Top, Right, Bottom; }
        [DllImport("user32.dll")] private static extern bool SetWindowPos(IntPtr h, IntPtr after, int x, int y, int w, int hgt, uint flags);
        [DllImport("user32.dll")] private static extern bool IsZoomed(IntPtr h);
        [DllImport("user32.dll")] private static extern bool IsIconic(IntPtr h);
        [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr h, out Rect rect);
        private Rectangle WindowBounds() {
            Rect r;
            if (GetWindowRect(Handle,out r)) return Rectangle.FromLTRB(r.Left,r.Top,r.Right,r.Bottom);
            return form.Bounds;
        }
        public WindowChrome(Form target) {
            form = target;
            form.Padding = new Padding(5);
            form.BackColor = Color.FromArgb(30, 23, 44);
            AssignHandle(form.Handle);
            SetWindowPos(Handle, IntPtr.Zero, 0, 0, 0, 0, 0x37); // FRAMECHANGED, NOACTIVATE, NOMOVE, NOSIZE, NOZORDER
            normalBounds = WindowBounds();
        }
        protected override void WndProc(ref Message m) {
            if (m.Msg == 5) { // WM_SIZE: WinForms assumes a caption when restoring client bounds.
                int next=m.WParam.ToInt32(), previous=lastSizeState;
                Rectangle saved=normalBounds;
                lastSizeState=next;
                base.WndProc(ref m);
                if (next==0) {
                    if (previous!=0 && saved.Width>0) {
                        form.BeginInvoke((Action)(() => {
                            if (!form.IsDisposed && form.WindowState==FormWindowState.Normal) {
                                SetWindowPos(Handle,IntPtr.Zero,saved.X,saved.Y,saved.Width,saved.Height,0x14);
                                normalBounds=WindowBounds();
                            }
                        }));
                    } else normalBounds=WindowBounds();
                }
                return;
            }
            if (m.Msg == 3 && lastSizeState==0 && !IsIconic(Handle) && !IsZoomed(Handle)) {
                normalBounds=WindowBounds();
            }
            if (m.Msg == 0x83) { // WM_NCCALCSIZE, including the simple RECT variant
                if (IsZoomed(Handle)) {
                    Rectangle work = Screen.FromHandle(Handle).WorkingArea;
                    Rect r = new Rect { Left=work.Left, Top=work.Top, Right=work.Right, Bottom=work.Bottom };
                    Marshal.StructureToPtr(r, m.LParam, false);
                }
                m.Result = IntPtr.Zero;
                return;
            }
            if (m.Msg == 0x84 && !IsZoomed(Handle)) { // WM_NCHITTEST on the uncovered 5px frame
                long packed=m.LParam.ToInt64();
                Point p=form.PointToClient(new Point((short)(packed & 0xffff),(short)((packed >> 16) & 0xffff)));
                bool l=p.X<5, r=p.X>=form.ClientSize.Width-5, t=p.Y<5, b=p.Y>=form.ClientSize.Height-5;
                int hit=t?(l?13:r?14:12):b?(l?16:r?17:15):l?10:r?11:1;
                m.Result=(IntPtr)hit;
                return;
            }
            base.WndProc(ref m);
        }
    }
}
