package com.example.myapplication3.database;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

public class GitSelfDatabaseHelper extends SQLiteOpenHelper {

    public static final String DATABASE_NAME = "Git_Self.db";
    private static final int DATABASE_VERSION = 2;

    private static GitSelfDatabaseHelper instance;

    private static final String TABLE_SAVED = "saved";

    private static final String COLUMN_ID = "id";
    private static final String COLUMN_DATA = "data";
    private static final String COLUMN_TEXT = "text";
    private static final String COLUMN_THEME = "theme";
    private static final String COLUMN_TIMESTAMP = "timestamp";

    private static final String CREATE_TABLE_SAVED = "CREATE TABLE " + TABLE_SAVED + " (" +
            COLUMN_ID + " INTEGER PRIMARY KEY AUTOINCREMENT, " +
            COLUMN_DATA + " TEXT, " +
            COLUMN_TEXT + " TEXT, " +
            COLUMN_THEME + " TEXT)";

    

    public GitSelfDatabaseHelper(Context context) {
        super(context, DATABASE_NAME, null, DATABASE_VERSION);
        instance = this;
    }

    public static synchronized GitSelfDatabaseHelper getInstance(Context context) {
        if (instance == null) {
            instance = new GitSelfDatabaseHelper(context);
        }
        return instance;
    }

    public static synchronized void resetInstance() {
        if (instance != null) {
            instance.close();
            instance = null;
        }
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL(CREATE_TABLE_SAVED);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // no-op for collect table removal
    }

    public long insertSavedRecord(String data, String text, String theme) {
        SQLiteDatabase db = this.getWritableDatabase();
        
        Cursor cursor = db.query(TABLE_SAVED, new String[]{COLUMN_ID}, 
                COLUMN_DATA + " = ? AND " + COLUMN_THEME + " = ?", 
                new String[]{data, theme}, null, null, null);
        
        if (cursor.moveToFirst()) {
            int existingId = cursor.getInt(cursor.getColumnIndexOrThrow(COLUMN_ID));
            cursor.close();
            
            ContentValues values = new ContentValues();
            values.put(COLUMN_TEXT, text);
            int rowsUpdated = db.update(TABLE_SAVED, values, 
                    COLUMN_ID + " = ?", new String[]{String.valueOf(existingId)});
            
            if (rowsUpdated > 0) {
                return existingId;
            }
        }
        cursor.close();
        
        ContentValues values = new ContentValues();
        values.put(COLUMN_DATA, data);
        values.put(COLUMN_TEXT, text);
        values.put(COLUMN_THEME, theme);
        long id = db.insert(TABLE_SAVED, null, values);
        return id;
    }

    public Cursor getSavedRecords() {
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor cursor = db.query(TABLE_SAVED, null, null, null, null, null, COLUMN_ID + " DESC");
        return cursor;
    }

    public void deleteSavedRecordById(int id) {
        SQLiteDatabase db = this.getWritableDatabase();
        db.delete(TABLE_SAVED, COLUMN_ID + " = ?", new String[]{String.valueOf(id)});
    }
    // collect-related database code removed
}
