package com.example.myapplication3.ui.home;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;

import androidx.annotation.NonNull;
import androidx.fragment.app.Fragment;

import com.example.myapplication3.R;

/**
 * Placeholder fragment after post-edit functionality was removed.
 */
public class PostEditFragment extends Fragment {

    public PostEditFragment() {
    }

    @Override
    public View onCreateView(@NonNull LayoutInflater inflater,
                             ViewGroup container, Bundle savedInstanceState) {
        // Use a built-in simple layout to avoid relying on project resource IDs
        View root = inflater.inflate(android.R.layout.simple_list_item_1, container, false);
        android.widget.TextView tv = root.findViewById(android.R.id.text1);
        tv.setText("已移除：发帖编辑页面");
        tv.setGravity(android.view.Gravity.CENTER);
        return root;
    }

}