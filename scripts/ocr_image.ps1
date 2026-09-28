# OCR an image with the Windows built-in engine (WinRT).
# Usage: powershell -NoProfile -File scripts/ocr_image.ps1 <image-path>

param([string]$Path)

Add-Type -AssemblyName System.Runtime.WindowsRuntime

[Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null
[Windows.Storage.StorageFile, Windows.Foundation, ContentType = WindowsRuntime] | Out-Null

function Await($WinRtTask, $ResultType) {
    $asTaskGeneric = (
        [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq 'AsTask' -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
        }
    )[0]

    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()

if ($null -eq $engine) {
    Write-Output 'OCR_ENGINE_NULL'
    exit 1
}

$file = Await (
    [Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)
) ([Windows.Storage.StorageFile])

$stream = Await (
    $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
) ([Windows.Storage.Streams.IRandomAccessStream])

$decoder = Await (
    [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
) ([Windows.Graphics.Imaging.BitmapDecoder])

$bitmap = Await (
    $decoder.GetSoftwareBitmapAsync()
) ([Windows.Graphics.Imaging.SoftwareBitmap])

$result = Await (
    $engine.RecognizeAsync($bitmap)
) ([Windows.Media.Ocr.OcrResult])

# Output one line per OCR line: "<x> <y> <text>" using the line's
# first-word bounding box origin, so callers can filter by region.
foreach ($line in $result.Lines) {
    $x = $null
    $y = $null

    foreach ($word in $line.Words) {
        if ($null -ne $word.BoundingRect) {
            $x = [double]$word.BoundingRect.X
            $y = [double]$word.BoundingRect.Y
            break
        }
    }

    $text = ($line.Words | ForEach-Object { $_.Text }) -join ' '

    if ($null -ne $x) {
        Write-Output ("{0} {1} {2}" -f [int]$x, [int]$y, $text)
    } else {
        Write-Output ("0 0 {0}" -f $text)
    }
}
