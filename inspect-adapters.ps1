$ErrorActionPreference='Stop'
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class N1xAdapterMemory {
    public string Name;
    public long DedicatedVideoBytes, DedicatedSystemBytes, SharedSystemBytes;
}
public static class N1xDxgi {
    [DllImport("dxgi.dll")]
    static extern int CreateDXGIFactory1(ref Guid iid, out IntPtr factory);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int EnumAdapters1(IntPtr self, uint index, out IntPtr adapter);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    delegate int GetDesc1(IntPtr self, IntPtr description);
    static IntPtr Method(IntPtr obj,int slot) { return Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*IntPtr.Size); }
    public static N1xAdapterMemory[] Read() {
        if (IntPtr.Size!=8) throw new Exception("Requires a 64-bit process");
        Guid iid=new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
        IntPtr factory;
        Marshal.ThrowExceptionForHR(CreateDXGIFactory1(ref iid,out factory));
        var rows=new List<N1xAdapterMemory>();
        try {
            var enumerate=(EnumAdapters1)Marshal.GetDelegateForFunctionPointer(Method(factory,12),typeof(EnumAdapters1));
            for (uint index=0;;index++) {
                IntPtr adapter;
                int hr=enumerate(factory,index,out adapter);
                if (hr==unchecked((int)0x887a0002)) break;
                Marshal.ThrowExceptionForHR(hr);
                try {
                    IntPtr desc=Marshal.AllocHGlobal(312);
                    try {
                        var get=(GetDesc1)Marshal.GetDelegateForFunctionPointer(Method(adapter,10),typeof(GetDesc1));
                        Marshal.ThrowExceptionForHR(get(adapter,desc));
                        rows.Add(new N1xAdapterMemory {Name=Marshal.PtrToStringUni(desc),DedicatedVideoBytes=Marshal.ReadInt64(desc,272),DedicatedSystemBytes=Marshal.ReadInt64(desc,280),SharedSystemBytes=Marshal.ReadInt64(desc,288)});
                    } finally { Marshal.FreeHGlobal(desc); }
                } finally { Marshal.Release(adapter); }
            }
        } finally { Marshal.Release(factory); }
        return rows.ToArray();
    }
}
'@
$rows=[N1xDxgi]::Read()
$rows | ConvertTo-Json -Depth 5 | Set-Content "$PSScriptRoot/results/windows-adapter-memory.json" -Encoding UTF8
$rows | Select-Object Name,@{n='DedicatedVideoGiB';e={$_.DedicatedVideoBytes/1GB}},@{n='DedicatedSystemGiB';e={$_.DedicatedSystemBytes/1GB}},@{n='SharedSystemGiB';e={$_.SharedSystemBytes/1GB}} | Format-Table -AutoSize
