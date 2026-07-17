/**
 * Code.gs — Google Apps Script para Gestión de Camiones
 * v5.1 — 10/11 columnas. Lee estado_servicio de col K si existe.
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

function actionGetAll(sheet) {
  var range = sheet.getDataRange();
  var rows = range.getValues();
  if (rows.length < 1) return [];
  var result = [];
  for (var i = 1; i < rows.length; i++) {
    var row = rows[i];
    if (!row.some(function(c) { return c !== "" && c !== null; })) continue;
    var obj = {
      fila_id: i + 1,
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
    result.push(obj);
  }
  return result;
}

function actionGetRow(sheet, fila) {
  if (fila < 1) throw new Error("fila debe ser >= 1");
  var numCols = Math.max(sheet.getLastColumn(), 10);
  var row = sheet.getRange(fila, 1, 1, numCols).getValues()[0];
  if (!row) throw new Error("Fila " + fila + " no encontrada");
  var obj = {
    fila_id: fila,
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

function actionAppend(sheet, values) {
  if (!values || values.length < 10) throw new Error("Se requieren 10+ valores");
  sheet.appendRow(values.map(function(v) { return v !== null && v !== undefined ? v : ""; }));
  return { fila_insertada: sheet.getLastRow() };
}

function actionUpdate(sheet, fila, values) {
  if (!fila || fila < 2) throw new Error("fila debe ser >= 2");
  if (!values || values.length < 10) throw new Error("Se requieren 10+ valores");
  var flat = values.map(function(v) { return v !== null && v !== undefined ? v : ""; });
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
  sheet.getRange(1, 1, 1, headers.length).setValues([headers]);
  return { cabeceras_escritas: headers };
}

function actionSetAll(sheet, headers, data) {
  if (!headers || headers.length < 10) throw new Error("Se requieren 10+ cabeceras");
  if (!data || !data.length) throw new Error("data vacío");
  var numCols = headers.length;
  var allRows = [headers];
  for (var i = 0; i < data.length; i++) {
    var row = data[i];
    var flat = [];
    for (var j = 0; j < numCols; j++)
      flat.push(j < row.length ? (row[j] != null ? row[j] : "") : "");
    allRows.push(flat);
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
