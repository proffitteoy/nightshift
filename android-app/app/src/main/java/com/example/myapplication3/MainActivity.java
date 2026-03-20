package com.example.myapplication3;

import android.graphics.Color;
import android.os.Bundle;
import android.view.Gravity;
import android.view.MenuItem;
import android.view.View;
import android.widget.TextView;
import android.widget.Toast;

import androidx.appcompat.app.ActionBar;
import androidx.appcompat.app.AppCompatActivity;

import com.google.android.material.navigation.NavigationView;
import androidx.navigation.NavController;
import androidx.navigation.Navigation;
import androidx.navigation.ui.AppBarConfiguration;
import androidx.navigation.ui.NavigationUI;
import androidx.drawerlayout.widget.DrawerLayout;

import com.example.myapplication3.databinding.ActivityMainBinding;
import com.example.myapplication3.database.DatabaseHelper;
import com.example.myapplication3.database.DatabaseUpdateManager;
import com.example.myapplication3.database.GitSelfDatabaseHelper;

public class MainActivity extends AppCompatActivity {

    private ActivityMainBinding binding;
    private NavController navController;
    private AppBarConfiguration appBarConfiguration;
    private DrawerLayout drawerLayout;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        binding = ActivityMainBinding.inflate(getLayoutInflater());
        setContentView(binding.getRoot());

        setupActionBar();

        drawerLayout = findViewById(R.id.drawer_layout);
        NavigationView navView = findViewById(R.id.nav_view);
        
        appBarConfiguration = new AppBarConfiguration.Builder(
                R.id.navigation_chat, R.id.navigation_home, R.id.navigation_dashboard, R.id.navigation_notifications)
                .setOpenableLayout(drawerLayout)
                .build();
        
        navController = Navigation.findNavController(this, R.id.nav_host_fragment_activity_main);
        // 移除对setupActionBarWithNavController的调用，因为我们没有通过setSupportActionBar()设置ActionBar
        NavigationUI.setupWithNavController(navView, navController);

        setupNavigationListener();
    }

    @Override
    public boolean onCreateOptionsMenu(android.view.Menu menu) {
        getMenuInflater().inflate(R.menu.main_menu, menu);
        return true;
    }

    @Override
    public boolean onSupportNavigateUp() {
        // 直接处理返回逻辑，不使用NavigationUI.navigateUp()，因为它依赖于ActionBar
        if (drawerLayout != null) {
            drawerLayout.openDrawer(androidx.core.view.GravityCompat.START);
            return true;
        }
        return super.onSupportNavigateUp();
    }

    private void setupNavItemSelectedListener() {
        // 移除自定义的OnNavigationItemSelectedListener，使用NavigationUI.setupWithNavController设置的默认监听器
        // 这样可以确保侧边栏的选中状态能够正确更新
    }

    private void setupNavigationListener() {
        navController.addOnDestinationChangedListener((controller, destination, arguments) -> {
            int destinationId = destination.getId();
            boolean isTopLevelDestination = appBarConfiguration.getTopLevelDestinations().contains(destinationId);
            
            // 移除对ActionBar的依赖，因为我们没有通过setSupportActionBar()设置ActionBar
        });
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == android.R.id.home) {
            // 点击返回按钮时打开侧边栏
            if (drawerLayout != null) {
                drawerLayout.openDrawer(androidx.core.view.GravityCompat.START);
                return true;
            }
        } else if (item.getItemId() == R.id.action_refresh) {
            refreshDatabase();
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    private void refreshDatabase() {
        Toast.makeText(this, "正在刷新数据库...", Toast.LENGTH_SHORT).show();
        
        DatabaseUpdateManager updateManager = new DatabaseUpdateManager(this);
        new Thread(() -> {
            updateManager.forceUpdateDatabases(new DatabaseUpdateManager.UpdateCallback() {
                @Override
                public void onUpdateSuccess() {
                    runOnUiThread(() -> {
                        Toast.makeText(MainActivity.this, "数据库刷新成功", Toast.LENGTH_SHORT).show();
                        DatabaseHelper.resetInstance();
                        GitSelfDatabaseHelper.resetInstance();
                        navController.navigate(R.id.navigation_home);
                    });
                }
                
                @Override
                public void onUpdateFailed(String error) {
                    runOnUiThread(() -> {
                        Toast.makeText(MainActivity.this, "刷新失败: " + error, Toast.LENGTH_SHORT).show();
                    });
                }
                
                @Override
                public void onProgress(int progress) {
                    
                }
                
                @Override
                public void onNoUpdateNeeded() {
                    runOnUiThread(() -> {
                        Toast.makeText(MainActivity.this, "数据库已是最新", Toast.LENGTH_SHORT).show();
                    });
                }
            });
        }).start();
    }

    private void setupActionBar() {
        ActionBar actionBar = getSupportActionBar();
        if (actionBar != null) {
            actionBar.setDisplayOptions(ActionBar.DISPLAY_SHOW_CUSTOM);
            actionBar.setDisplayHomeAsUpEnabled(false);
            actionBar.setHomeButtonEnabled(false);
            actionBar.setElevation(0);

            TextView titleView = new TextView(this);
            titleView.setText("My Application3");
            titleView.setTextSize(13);
            titleView.setTypeface(null, android.graphics.Typeface.BOLD);
            titleView.setTextColor(Color.BLACK);
            titleView.setGravity(Gravity.CENTER);
            titleView.setPadding(0, 8, 0, 8);

            ActionBar.LayoutParams params = new ActionBar.LayoutParams(
                    ActionBar.LayoutParams.MATCH_PARENT,
                    ActionBar.LayoutParams.MATCH_PARENT,
                    Gravity.CENTER);
            actionBar.setCustomView(titleView, params);
        }
    }

    public void openDrawer() {
        if (drawerLayout != null) {
            drawerLayout.openDrawer(androidx.core.view.GravityCompat.START);
        }
    }

}
