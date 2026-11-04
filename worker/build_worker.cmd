@echo off
rem Builds QwenRemoteWorker.exe and GladiaSttWorker.exe with the C# compiler that ships with Windows (.NET Framework 4).
cd /d "%~dp0"
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" -nologo -optimize -platform:x64 -target:exe ^
  -r:System.Web.Extensions.dll -out:QwenRemoteWorker.exe QwenRemoteWorker.cs || exit /b 1
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" -nologo -optimize -platform:x64 -target:exe ^
  -r:System.Web.Extensions.dll -out:GladiaSttWorker.exe GladiaSttWorker.cs
