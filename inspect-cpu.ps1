$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
public class N1xCpuSet {
    public int Id, Group, LogicalProcessor, Core, EfficiencyClass, SchedulingClass;
    public bool Parked;
}
public static class N1xCpuTopology {
    [DllImport("kernel32.dll", SetLastError=true)]
    static extern bool GetSystemCpuSetInformation(IntPtr info, uint length, out uint returned, IntPtr process, uint flags);
    public static N1xCpuSet[] Read() {
        uint needed;
        GetSystemCpuSetInformation(IntPtr.Zero,0,out needed,IntPtr.Zero,0);
        if (needed==0) throw new Win32Exception(Marshal.GetLastWin32Error());
        IntPtr buffer=Marshal.AllocHGlobal((int)needed);
        try {
            uint returned;
            if (!GetSystemCpuSetInformation(buffer,needed,out returned,IntPtr.Zero,0)) throw new Win32Exception(Marshal.GetLastWin32Error());
            var rows=new List<N1xCpuSet>();
            for (int offset=0; offset<returned;) {
                IntPtr row=IntPtr.Add(buffer,offset);
                int size=Marshal.ReadInt32(row,0);
                if (size<8 || offset+size>returned) throw new Exception("Invalid CPU-set record size");
                if (Marshal.ReadInt32(row,4)==0 && size>=32) {
                    rows.Add(new N1xCpuSet { Id=Marshal.ReadInt32(row,8), Group=(ushort)Marshal.ReadInt16(row,12), LogicalProcessor=Marshal.ReadByte(row,14), Core=Marshal.ReadByte(row,15), EfficiencyClass=Marshal.ReadByte(row,18), SchedulingClass=Marshal.ReadByte(row,20), Parked=(Marshal.ReadByte(row,19)&1)!=0 });
                }
                offset+=size;
            }
            return rows.ToArray();
        } finally { Marshal.FreeHGlobal(buffer); }
    }
}
'@
$rows=[N1xCpuTopology]::Read()
$rows | ConvertTo-Json -Depth 5 | Set-Content "$PSScriptRoot/results/windows-cpu-topology.json" -Encoding UTF8
$rows | Format-Table LogicalProcessor,Core,EfficiencyClass,SchedulingClass,Parked -AutoSize
