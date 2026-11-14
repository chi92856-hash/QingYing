param([Parameter(Mandatory=$true)][string]$ScriptPath)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$runtimePath = Join-Path $projectRoot '清影\_internal'
$scriptFile = (Resolve-Path -LiteralPath $ScriptPath).Path
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class QingyingPython {
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern bool SetDllDirectory(string path);
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    public static extern IntPtr LoadLibrary(string path);
    [DllImport("kernel32", CharSet=CharSet.Ansi)]
    public static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("python310", CallingConvention=CallingConvention.Cdecl, CharSet=CharSet.Unicode)]
    public static extern void Py_SetPath(string path);
    [DllImport("python310", CallingConvention=CallingConvention.Cdecl)]
    public static extern void Py_InitializeEx(int signals);
    [DllImport("python310", CallingConvention=CallingConvention.Cdecl)]
    public static extern int PyRun_SimpleString(byte[] code);
    [DllImport("python310", CallingConvention=CallingConvention.Cdecl)]
    public static extern int Py_FinalizeEx();
}
'@
[QingyingPython]::SetDllDirectory($runtimePath) | Out-Null
$pythonLibrary = [QingyingPython]::LoadLibrary((Join-Path $runtimePath 'python310.dll'))
if ($pythonLibrary -eq [IntPtr]::Zero) {
    throw 'Cannot load bundled Python 3.10 runtime.'
}
[Runtime.InteropServices.Marshal]::WriteInt32([QingyingPython]::GetProcAddress($pythonLibrary, 'Py_NoSiteFlag'), 1)
[Runtime.InteropServices.Marshal]::WriteInt32([QingyingPython]::GetProcAddress($pythonLibrary, 'Py_IgnoreEnvironmentFlag'), 1)
[QingyingPython]::Py_SetPath("$runtimePath\base_library.zip;$runtimePath;$projectRoot\source;$projectRoot\tests;$projectRoot\tools")
[QingyingPython]::Py_InitializeEx(0)
$pythonLiteral = "'" + $scriptFile.Replace('\','/').Replace("'","\'") + "'"
$bootstrapLiteral = "'" + (Join-Path $PSScriptRoot 'bundle_bootstrap.py').Replace('\','/').Replace("'","\'") + "'"
$code = "import sys; sys.argv=[$pythonLiteral]; exec(compile(open($bootstrapLiteral, encoding='utf-8').read(), $bootstrapLiteral, 'exec'))"
$result = [QingyingPython]::PyRun_SimpleString([Text.Encoding]::UTF8.GetBytes($code + [char]0))
$finalResult = [QingyingPython]::Py_FinalizeEx()
if ($result -ne 0 -or $finalResult -ne 0) { exit 1 }
