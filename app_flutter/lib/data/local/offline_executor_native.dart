import 'dart:io';
import 'package:drift/drift.dart';
import 'package:drift/native.dart';

QueryExecutor openOfflineFile(String path) =>
    NativeDatabase.createInBackground(File(path));
