/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 * v5.2 — Detecta Ruta en col D; lee estado_servicio de col K si existe.
 */

var API_TOKEN = "pablo9090";

var SPREADSHEET_ID = "1g9nAeqyimh5VMwkfane8kPstHedFIHKDE0C7HL5KhFw";
var SHEET_NAME = "Hoja1";

function doGet(e) { return handleRequest(e, 'get'); }
function doPost(e) { return handleRequest(e, 'post'); }

function handleRequest(e, method) {
  try {
    var data = method === 'get' ? e.parameter : JSON.parse(e.postData.contents);
    if (data.token !== API_TOKEN)
      return respondJson({ success: false, error: "Token inválido" }, 403);
    if (!data.action)
      return respondJson({ success: false, error: "action requerido" }, 400);

    var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
    var sheet = ss.getSheetByName(SHEET_NAME);
    if (!sheet) sheet = ss.getSheets()[0];

    var result;
    switch (data.action) {
      case 'getAll': result = actionGetAll(sheet); break;
      case 'getRow': result = actionGetRow(sheet, parseInt(data.fila)); break;
      case 'append': result = actionAppend(sheet, data.values); break;
      case 'update': result = actionUpdate(sheet, data.fila, data.values); break;
      case 'clear': result = actionClear(sheet); break;
      case 'writeHeaders': result = actionWriteHeaders(sheet, data.headers); break;
      case 'setAll': result = actionSetAll(sheet, data.headers, data.data); break;
      case 'deleteRow': result = actionDeleteRow(sheet, data.fila); break;
      default: return respondJson({ success: false, error: "acción desconocida" }, 400);
    }
    return respondJson({ success: true, data: result });
  } catch (err) {
    return respondJson({ success: false, error: err.toString() }, 500);
  }
}

function detectFormat(headers) {
  // Col D (index 3) es "Ruta"? → legacy 11-columnas
  return String(headers[3] || "").trim().toLowerCase() === "ruta" ? 11 : 10;
}

function rowToObj(row, filaId, fmt) {
  if (fmt === 11) {
    return {
      fila_id: filaId,
      nro: String(row[0] || ""),
      placa: String(row[1] || ""),
      estado_trabajo: String(row[2] || "Fijo"),
      tipo_combustible: String(row[4] || "GAS-GASOLINA"),
      costo_flete: parseFloat(row[5]) || 0,
      sucursal: String(row[6] || ""),
      capacidad_kg: parseInt(row[7]) || 0,
      capacidad_maples: parseInt(row[8]) || 0,
      capacidad_util_kg: parseFloat(row[9]) || 0,
      sistema_camion: String(row[10] || ""),
    };
  }
  var obj = {
    fila_id: filaId,
    nro: String(row[0] || ""),
    placa: String(row[1] || ""),
    estado_trabajo: String(row[2] || "Fijo"),
    tipo_combustible: String(row[3] || "GAS-GASOLINA"),
    costo_flete: parseFloat(row[4]) || 0,
    sucursal: String(row[5] || ""),
    capacidad_kg: parseInt(row[6]) || 0,
    capacidad_maples: parseInt(row[7]) || 0,
    capacidad_util_kg: parseFloat(row[8]) || 0,
    sistema_camion: String(row[9] || ""),
  };
  if (row.length > 10) obj.estado_servicio = String(row[10] || "");
  return obj;
}

function actionGetAll(sheet) {
  var range = sheet.getDataRange();
  var rows = range.getValues();
  if (rows.length < 1) return [];
  var fmt = detectFormat(rows[0]);
  var result = [];
  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(c) { return c !== "" && c !== null; })) continue;
    result.push(rowToObj(row, i + 1, fmt));
  }
  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");
  var numCols = Math.max(sheet.getLastColumn(), 10);
  var headers = sheet.getRange(1, 1, 1, numCols).getValues()[0];
  var fmt = detectFormat(headers);
  var row = sheet.getRange(fila, 1, 1, numCols).getValues()[0];
  if (!row) throw new Error("Fila " + fila + " no encontrada");
  return rowToObj(row, fila, fmt);
}

function actionAppend(sheet, values) {
  if (!values || values.length < 10) throw new Error("Se requieren 10+ valores");
  var numCols = Math.max(sheet.getLastColumn(), values.length);
  if (numCols >= 11) {
    var fmt = detectFormat(sheet.getRange(1, 1, 1, numCols).getValues()[0]);
    if (fmt === 11) {
      // Legacy Ruta: insertar espacio en col D
      var p = [];
      for (var j = 0; j < numCols; j++) {
        if (j === 3) { p.push(""); continue; }
        var src = j > 3 ? j - 1 : j;
        p.push(src < values.length ? (values[src] != null ? values[src] : "") : "");
      }
      sheet.appendRow(p);
      return { fila_insertada: sheet.getLastRow() };
    }
  }
  sheet.appendRow(values.map(function(v) { return v != null ? v : ""; }));
  return { fila_insertada: sheet.getLastRow() };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < 10) throw new Error("Se requieren 10+ valores");
  var numCols = Math.max(sheet.getLastColumn(), values.length);
  if (numCols >= 11) {
    var fmt = detectFormat(sheet.getRange(1, 1, 1, numCols).getValues()[0]);
    if (fmt === 11) {
      var p = [];
      for (var j = 0; j < numCols; j++) {
        if (j === 3) { p.push(""); continue; }
        var src = j > 3 ? j - 1 : j;
        p.push(src < values.length ? (values[src] != null ? values[src] : "") : "");
      }
      sheet.getRange(fila, 1, 1, numCols).setValues([p]);
      return { fila_actualizada: fila };
    }
  }
  var flat = values.map(function(v) { return v != null ? v : ""; });
  sheet.getRange(fila, 1, 1, flat.length).setValues([flat]);
  return { fila_actualizada: fila };
}

function actionClear(sheet) {
  var lr = sheet.getLastRow();
  if (lr > 1) sheet.getRange(2, 1, lr - 1, sheet.getLastColumn()).clearContent();
  return { filas_limpiadas: lr - 1 };
}

function actionWriteHeaders(sheet, headers) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10+ cabeceras");
  var numCols = Math.max(sheet.getLastColumn(), headers.length);
  if (numCols >= 11) {
    var fmt = detectFormat(sheet.getRange(1, 1, 1, numCols).getValues()[0]);
    if (fmt === 11) {
      var p = [];
      for (var j = 0; j < numCols; j++) {
        if (j === 3) { p.push("Ruta"); continue; }
        var src = j > 3 ? j - 1 : j;
        p.push(src < headers.length ? headers[src] : "");
      }
      sheet.getRange(1, 1, 1, numCols).setValues([p]);
      return { cabeceras_escritas: headers };
    }
  }
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  return { cabeceras_escritas: headers };
}

function actionSetAll(sheet, headers, data) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10+ cabeceras");
  if (!data || !data.length) throw new Error("data vacío");
  var numCols = Math.max(sheet.getLastColumn(), headers.length);
  var fmt = (numCols >= 11) ? detectFormat(sheet.getRange(1, 1, 1, numCols).getValues()[0]) : 10;
  var allRows = [];
  if (fmt === 11) {
    var h = [];
    for (var j = 0; j < numCols; j++) {
      if (j === 3) { h.push("Ruta"); continue; }
      var src = j > 3 ? j - 1 : j;
      h.push(src < headers.length ? headers[src] : "");
    }
    allRows.push(h);
  } else {
    var h2 = [];
    for (var j = 0; j < numCols; j++)
      h2.push(j < headers.length ? headers[j] : "");
    allRows.push(h2);
  }
  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    if (fmt === 11) {
      var r = [];
      for (var j = 0; j < numCols; j++) {
        if (j === 3) { r.push(""); continue; }
        var src = j > 3 ? j - 1 : j;
        r.push(src < row.length ? (row[src] != null ? row[src] : "") : "");
      }
      allRows.push(r);
    } else {
      var r2 = [];
      for (var j = 0; j < numCols; j++)
        r2.push(j < row.length ? (row[j] != null ? row[j] : "") : "");
      allRows.push(r2);
    }
  }
  sheet.getRange(1, 1, allRows.length, numCols).setValues(allRows);
  return { filas_escritas: data.length };
}

function actionDeleteRow(sheet, fila) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  sheet.deleteRow(fila);
  return { fila_eliminada: fila };
}

function respondJson(data, code) {
  var out = ContentService.createTextOutput(JSON.stringify(data));
  out.setMimeType(ContentService.MimeType.JSON);
  return out;
}
