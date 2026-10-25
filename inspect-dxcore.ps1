$ErrorActionPreference='Stop'
# Read-only DXCore inspection; includes NPUs that DXGI may omit.
# ABI: microsoft/DirectX-Headers, include/directx/dxcore_interface.h.
if (-not ('N1xDxCore' -as [type])) { Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public static class N1xDxCore {
    [DllImport("dxcore.dll")] static extern int DXCoreCreateAdapterFactory(ref Guid iid, out IntPtr factory);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateList(IntPtr self,uint count,ref Guid attribute,ref Guid iid,out IntPtr list);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint GetCount(IntPtr self);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetAdapter(IntPtr self,uint index,ref Guid iid,out IntPtr adapter);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] [return: MarshalAs(UnmanagedType.U1)] delegate bool HasProperty(IntPtr self,uint property);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] [return: MarshalAs(UnmanagedType.U1)] delegate bool HasAttribute(IntPtr self,ref Guid attribute);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetSize(IntPtr self,uint property,out UIntPtr size);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetProperty(IntPtr self,uint property,UIntPtr size,IntPtr data);
    static Delegate Method(IntPtr obj,int slot,Type type) { return Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*IntPtr.Size),type); }
    static byte[] Property(IntPtr adapter,uint property) {
        if (!((HasProperty)Method(adapter,5,typeof(HasProperty)))(adapter,property)) return null;
        UIntPtr size;
        Marshal.ThrowExceptionForHR(((GetSize)Method(adapter,7,typeof(GetSize)))(adapter,property,out size));
        int bytes=checked((int)size.ToUInt64());
        IntPtr data=Marshal.AllocHGlobal(bytes);
        try {
            Marshal.ThrowExceptionForHR(((GetProperty)Method(adapter,6,typeof(GetProperty)))(adapter,property,size,data));
            byte[] result=new byte[bytes]; Marshal.Copy(data,result,0,bytes); return result;
        } finally { Marshal.FreeHGlobal(data); }
    }
    static object Memory(IntPtr adapter,uint property) {
        byte[] value=Property(adapter,property);
        return value==null ? null : (object)BitConverter.ToUInt64(value,0);
    }
    static bool Attribute(IntPtr adapter,string value) {
        Guid attribute=new Guid(value);
        return ((HasAttribute)Method(adapter,4,typeof(HasAttribute)))(adapter,ref attribute);
    }
    public static object[] Read() {
        Guid factoryId=new Guid("78ee5945-c36e-4b13-a669-005dd11c0f06"),listId=new Guid("526c7776-40e9-459b-b711-f32ad76dfc28"),adapterId=new Guid("f0db4c7f-fe5a-42a2-bd62-f2a6cf6fc83e");
        IntPtr factory; Marshal.ThrowExceptionForHR(DXCoreCreateAdapterFactory(ref factoryId,out factory));
        var rows=new List<object>();
        try {
            foreach (string kind in new string[]{"b69eb219-3ded-4464-979f-a00bd4687006","d46140c4-add7-451b-9e56-06fe8c3b58ed"}) {
                Guid attribute=new Guid(kind); IntPtr list;
                Marshal.ThrowExceptionForHR(((CreateList)Method(factory,3,typeof(CreateList)))(factory,1,ref attribute,ref listId,out list));
                try {
                    uint count=((GetCount)Method(list,4,typeof(GetCount)))(list);
                    for(uint i=0;i<count;i++) {
                        IntPtr adapter;
                        Marshal.ThrowExceptionForHR(((GetAdapter)Method(list,3,typeof(GetAdapter)))(list,i,ref adapterId,out adapter));
                        try {
                            var row=new Dictionary<string,object>();
                            row["name"]=System.Text.Encoding.UTF8.GetString(Property(adapter,2)).TrimEnd('\0');
                            row["dedicatedAdapterBytes"]=Memory(adapter,7);
                            row["dedicatedSystemBytes"]=Memory(adapter,8);
                            row["sharedSystemBytes"]=Memory(adapter,9);
                            row["isNpu"]=Attribute(adapter,"d46140c4-add7-451b-9e56-06fe8c3b58ed");
                            row["d3d12GenericML"]=Attribute(adapter,"b71b0d41-1088-422f-a27c-0250b7d3a988");
                            row["d3d12CoreCompute"]=Attribute(adapter,"248e2800-a793-4724-abaa-23a6de1be090");
                            rows.Add(row);
                        } finally { Marshal.Release(adapter); }
                    }
                } finally { Marshal.Release(list); }
            }
        } finally { Marshal.Release(factory); }
        return rows.ToArray();
    }
}
'@
}
$rows=[N1xDxCore]::Read()
$json=ConvertTo-Json -InputObject $rows -Depth 6
$json | Set-Content "$PSScriptRoot/results/windows-dxcore-memory.json" -Encoding UTF8
$json
