package com.example.myapplication3.database;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import java.text.ParseException;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;

public class DatabaseHelper extends SQLiteOpenHelper {

    public static final String DATABASE_NAME = "Hot_Git.db";
    private static final int DATABASE_VERSION = 2;

    private static DatabaseHelper instance;

    private static final String TABLE_NEW = "new";

    private static final String COLUMN_ID = "id";
    private static final String COLUMN_DATA = "data";
    private static final String COLUMN_TEXT = "text";
    private static final String COLUMN_THEME = "theme";

    private static final String CREATE_TABLE_NEW = "CREATE TABLE " + TABLE_NEW + " (" +
            COLUMN_ID + " INTEGER PRIMARY KEY AUTOINCREMENT, " +
            COLUMN_DATA + " TEXT, " +
            COLUMN_TEXT + " TEXT, " +
            COLUMN_THEME + " TEXT)";

    public DatabaseHelper(Context context) {
        super(context, DATABASE_NAME, null, DATABASE_VERSION);
        instance = this;
    }

    public static synchronized DatabaseHelper getInstance(Context context) {
        if (instance == null) {
            instance = new DatabaseHelper(context);
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
        db.execSQL(CREATE_TABLE_NEW);
        insertInitialData(db);
    }

    private void insertInitialData(SQLiteDatabase db) {
        ContentValues values = new ContentValues();
        values.put(COLUMN_DATA, "2026.1.15");
        values.put(COLUMN_TEXT, "111");
        values.put(COLUMN_THEME, "15号主题1");
        db.insert(TABLE_NEW, null, values);

        values.clear();
        values.put(COLUMN_DATA, "2026.1.15");
        values.put(COLUMN_TEXT, "222");
        values.put(COLUMN_THEME, "15号主题2");
        db.insert(TABLE_NEW, null, values);

        values.clear();
        values.put(COLUMN_DATA, "2026.1.16");
        values.put(COLUMN_TEXT, "333");
        values.put(COLUMN_THEME, "16号主题1");
        db.insert(TABLE_NEW, null, values);

        values.clear();
        values.put(COLUMN_DATA, "2026.1.17");
        values.put(COLUMN_TEXT, "444");
        values.put(COLUMN_THEME, "17号主题1");
        db.insert(TABLE_NEW, null, values);

        values.clear();
        values.put(COLUMN_DATA, "2026.1.18");
        values.put(COLUMN_TEXT, "555");
        values.put(COLUMN_THEME, "18号主题1");
        db.insert(TABLE_NEW, null, values);

        values.clear();
        values.put(COLUMN_DATA, "2026.1.18");
        values.put(COLUMN_TEXT, "66666666666666666666666666666666666666666666666666666666666666666666666");
        values.put(COLUMN_THEME, "18号主题2");
        db.insert(TABLE_NEW, null, values);
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
    }

    public Cursor getNewRecords() {
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor cursor = db.query(TABLE_NEW, null, null, null, null, null, COLUMN_ID + " DESC");
        return cursor;
    }



    public Cursor getRecentRecords() {
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor cursor = db.query(TABLE_NEW, null, null, null, null, null, COLUMN_ID + " DESC");
        return cursor;
    }

    public Cursor getRecentRecordsWithinWeek() {
        SQLiteDatabase db = this.getReadableDatabase();
        SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy.M.d");
        Calendar calendar = Calendar.getInstance();
        
        // 计算本周一的日期（更直接的方法）
        int dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK);
        int daysToMonday = (dayOfWeek == Calendar.SUNDAY) ? 6 : dayOfWeek - 2;
        calendar.add(Calendar.DAY_OF_YEAR, -daysToMonday);
        // 设置时间为00:00:00
        calendar.set(Calendar.HOUR_OF_DAY, 0);
        calendar.set(Calendar.MINUTE, 0);
        calendar.set(Calendar.SECOND, 0);
        calendar.set(Calendar.MILLISECOND, 0);
        Date monday = calendar.getTime();
        
        // 今天的日期
        Date today = new Date();
        
        ArrayList<String> recentRecords = new ArrayList<>();
        
        try {
            Cursor cursor = db.query(TABLE_NEW, null, null, null, null, null, null);
            
            while (cursor.moveToNext()) {
                String data = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_DATA));
                String theme = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_THEME));
                Date postDate = dateFormat.parse(data);

                // 设置帖子日期的时间为12:00:00，避免时区问题
                Calendar postCalendar = Calendar.getInstance();
                postCalendar.setTime(postDate);
                postCalendar.set(Calendar.HOUR_OF_DAY, 12);
                postCalendar.set(Calendar.MINUTE, 0);
                postCalendar.set(Calendar.SECOND, 0);
                postCalendar.set(Calendar.MILLISECOND, 0);
                postDate = postCalendar.getTime();
                
                boolean isWithinWeek = !postDate.before(monday) && !postDate.after(today);

                if (isWithinWeek) {
                    recentRecords.add(data);
                }
            }
            cursor.close();
        } catch (ParseException e) {
            e.printStackTrace();
        }
        
        if (recentRecords.isEmpty()) {
            return null;
        }
        
        String[] selectionArgs = recentRecords.toArray(new String[0]);
        StringBuilder selectionBuilder = new StringBuilder();
        for (int i = 0; i < selectionArgs.length; i++) {
            if (i > 0) {
                selectionBuilder.append(" OR ");
            }
            selectionBuilder.append(COLUMN_DATA).append(" = ?");
        }
        
        Cursor cursor = db.query(TABLE_NEW, null, selectionBuilder.toString(), selectionArgs, null, null, COLUMN_ID + " DESC");
        return cursor;
    }

    public Cursor getOldRecordsWithinThreeWeeks() {
        SQLiteDatabase db = this.getReadableDatabase();
        SimpleDateFormat dateFormat = new SimpleDateFormat("yyyy.M.d");
        Calendar calendar = Calendar.getInstance();
        
        // 计算本周一的日期（与getRecentRecordsWithinWeek方法使用相同的逻辑）
        int dayOfWeek = calendar.get(Calendar.DAY_OF_WEEK);
        int daysToMonday = (dayOfWeek == Calendar.SUNDAY) ? 6 : dayOfWeek - 2;
        calendar.add(Calendar.DAY_OF_YEAR, -daysToMonday);
        // 设置时间为00:00:00
        calendar.set(Calendar.HOUR_OF_DAY, 0);
        calendar.set(Calendar.MINUTE, 0);
        calendar.set(Calendar.SECOND, 0);
        calendar.set(Calendar.MILLISECOND, 0);
        Date currentMonday = calendar.getTime();
        
        // 计算三周前的周一日期
        calendar.add(Calendar.WEEK_OF_YEAR, -3);
        Date threeWeeksAgoMonday = calendar.getTime();
        
        
        ArrayList<String> oldRecords = new ArrayList<>();
        
        try {
            // 只检查new表中的记录
            Cursor cursor = db.query(TABLE_NEW, null, null, null, null, null, null);
            
            while (cursor.moveToNext()) {
                String data = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_DATA));
                String theme = cursor.getString(cursor.getColumnIndexOrThrow(COLUMN_THEME));
                Date postDate = dateFormat.parse(data);
                
                
                // 设置帖子日期的时间为12:00:00，避免时区问题
                Calendar postCalendar = Calendar.getInstance();
                postCalendar.setTime(postDate);
                postCalendar.set(Calendar.HOUR_OF_DAY, 12);
                postCalendar.set(Calendar.MINUTE, 0);
                postCalendar.set(Calendar.SECOND, 0);
                postCalendar.set(Calendar.MILLISECOND, 0);
                postDate = postCalendar.getTime();
                
                boolean isBeforeCurrentMonday = postDate.before(currentMonday);
                boolean isAfterThreeWeeksAgo = !postDate.before(threeWeeksAgoMonday);
                // 往期内容应该显示：
                // 1. 三周前到本周一之前的记录
                // 2. 未来的记录（比如28号）
                boolean isInRange = (isBeforeCurrentMonday && isAfterThreeWeeksAgo) || postDate.after(new Date());
                
                
                if (isInRange) {
                    oldRecords.add(data);
                }
            }
            cursor.close();
        } catch (ParseException e) {
            e.printStackTrace();
        }
        
        
        if (oldRecords.isEmpty()) {
            return null;
        }
        
        String[] selectionArgs = oldRecords.toArray(new String[0]);
        StringBuilder selectionBuilder = new StringBuilder();
        for (int i = 0; i < selectionArgs.length; i++) {
            if (i > 0) {
                selectionBuilder.append(" OR ");
            }
            selectionBuilder.append(COLUMN_DATA).append(" = ?");
        }
        
        // 只查询new表
        Cursor cursor = db.query(TABLE_NEW, null, selectionBuilder.toString(), selectionArgs, null, null, COLUMN_ID + " DESC");
        return cursor;
    }

    public void deleteNewRecordById(int id) {
        SQLiteDatabase db = this.getWritableDatabase();
        db.delete(TABLE_NEW, COLUMN_ID + " = ?", new String[]{String.valueOf(id)});
    }



    public void refreshDatabase() {
        close();
        getWritableDatabase();
    }


}
